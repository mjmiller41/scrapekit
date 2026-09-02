"""Tier 4: Steel (Docker, stealth Chromium) driven by Stagehand, with headless Claude Code as
the model. No API key: the model callback shells out to `claude -p` on the subscription.

Requires the `tier4` extra (`uv tool install --editable '.[tier4]'`) and a running Steel
container started by scripts/steel-up.sh, which mounts Stagehand's browser extension into
Steel's extensions folder so every session can preload it.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time

import httpx

from scrapekit.config import Config, load_config
from scrapekit.tiers import Page

STEEL_EXTENSION_NAME = "stagehand"


# ---------------------------------------------------------------- model callback

def flatten_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    parts = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "image":
            parts.append("[image omitted]")
    return "\n".join(parts)


def build_llm_prompt(params: dict) -> tuple[str, bool]:
    """Turn Stagehand's generate params into one prompt. Returns (prompt, structured)."""
    system = params.get("system_prompt") or ""
    convo = "\n\n".join(f"[{m['role']}]\n{flatten_content(m['content'])}" for m in params.get("messages", []))
    fmt = params.get("response_format") or {}
    structured = fmt.get("type") == "json_schema"
    prompt = (f"<system>\n{system}\n</system>\n\n" if system else "") + convo
    if structured:
        schema = fmt.get("schema") or {}
        prompt += (
            "\n\nRespond with ONLY a JSON object that validates against this JSON schema. "
            "No prose, no code fence.\n" + json.dumps(schema, ensure_ascii=False)
        )
    return prompt, structured


def json_from_text(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
        if not starts:
            raise ValueError("model reply contained no JSON")
        s = min(starts)
        e = max(text.rfind("}"), text.rfind("]"))
        text = text[s : e + 1]
    return json.loads(text)


def claude_call(prompt: str, model: str, timeout: float) -> tuple[str, dict]:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json", "--max-turns", "1", prompt],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
    envelope = json.loads(proc.stdout)
    return envelope.get("result", ""), envelope.get("usage", {})


def make_claude_generate(model: str, timeout: float, log=None):
    """Return an async LLMGenerateCallback for Stagehand backed by `claude -p`."""

    async def generate(params):
        if hasattr(params, "model_dump"):
            params = params.model_dump(by_alias=True, exclude_none=True)
        prompt, structured = build_llm_prompt(params)
        t0 = time.time()
        text, usage = await asyncio.to_thread(claude_call, prompt, model, timeout)
        if log:
            log(f"[tier4 llm] {'json' if structured else 'text'} {len(prompt)} chars in, {len(text)} out, {time.time() - t0:.1f}s")
        result = {
            "role": "assistant",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }
        if structured:
            data = json_from_text(text)
            return {**result, "output_format": "json_schema", "structured_content": data,
                    "content": [{"type": "text", "text": json.dumps(data)}]}
        return {**result, "output_format": "text", "content": [{"type": "text", "text": text}]}

    return generate


# ---------------------------------------------------------------- steel

def steel_session_start(steel_url: str) -> dict:
    with httpx.Client(base_url=steel_url, timeout=60) as c:
        r = c.post("/v1/sessions", json={"blockAds": True, "extensions": [STEEL_EXTENSION_NAME]})
        r.raise_for_status()
        sess = r.json()
    ws = sess["websocketUrl"]
    host = steel_url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
    sess["cdp_url"] = ws.replace("0.0.0.0", host)
    return sess


def steel_session_release(steel_url: str, session_id: str) -> None:
    with httpx.Client(base_url=steel_url, timeout=30) as c:
        c.post(f"/v1/sessions/{session_id}/release")


def steel_ok(steel_url: str) -> bool:
    try:
        with httpx.Client(base_url=steel_url, timeout=5) as c:
            return c.get("/v1/sessions").status_code == 200
    except httpx.HTTPError:
        return False


async def stagehand_extension_id(cdp_url: str) -> str:
    import websockets

    async with websockets.connect(cdp_url, max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        while True:
            r = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if r.get("id") == 1:
                break
    for t in r["result"]["targetInfos"]:
        if t["type"] == "service_worker" and "service-worker.js" in t["url"]:
            return t["url"].split("/")[2]
    raise RuntimeError("Stagehand extension is not loaded in the Steel session; rerun scripts/steel-up.sh")


# ---------------------------------------------------------------- tier 4

def tier4_stagehand(url: str, schema: dict, instruction: str = "", steps: list[str] | None = None, cfg: Config | None = None) -> Page:
    cfg = cfg or load_config()
    page = Page(url=url, tier=4)
    try:
        import stagehand  # noqa: F401
    except ImportError:
        page.error = "stagehand is not installed; run: uv tool install --editable '.[tier4]' in the scrapekit checkout"
        return page
    if not steel_ok(cfg.steel_url):
        page.error = f"Steel is not answering at {cfg.steel_url}; run scripts/steel-up.sh"
        return page
    return asyncio.run(_tier4_async(url, schema, instruction, steps or [], cfg))


async def _tier4_async(url: str, schema: dict, instruction: str, steps: list[str], cfg: Config) -> Page:
    from pydantic import create_model
    from stagehand import Stagehand, local_browser

    page = Page(url=url, tier=4)
    names = [f["name"] for f in schema.get("fields", [])]
    Item = create_model("Item", **{n: (str | None, None) for n in names})
    Items = create_model("Items", items=(list[Item], ...))
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731

    sess = steel_session_start(cfg.steel_url)
    try:
        ext_id = await stagehand_extension_id(sess["cdp_url"])
        browser = await local_browser.connect(cdp_url=sess["cdp_url"], extension_id=ext_id)
        try:
            sh = await Stagehand.create(
                browser=browser,
                model=make_claude_generate(cfg.tier4_model, cfg.timeout_seconds * 6, log),
            )
            try:
                pg = (await browser.context.pages())[0]
                resp = await pg.goto(url, timeout=int(cfg.timeout_seconds * 1000))
                page.status = getattr(resp, "status", None) or 200
                page.final_url = pg.url if isinstance(getattr(pg, "url", None), str) else url
                for step in steps:
                    log(f"[tier4 act] {step}")
                    await sh.act(step)
                task = instruction or "Extract every item on the page."
                hints = ", ".join(f"{f['name']}" + (f" ({f['description']})" if f.get("description") else "") for f in schema.get("fields", []))
                res = await sh.extract(f"{task} Fields: {hints}.", Items)
                page.rows = [{n: getattr(it, n) for n in names} for it in res.data.items]
                try:
                    page.html = await pg.content()
                except Exception:
                    pass
            finally:
                await sh.close()
        finally:
            await browser.close()
    except Exception as exc:
        page.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        steel_session_release(cfg.steel_url, sess["id"])
    return page
