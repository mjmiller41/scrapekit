"""One function per tier. Each returns a Page.

Tier 1: httpx + selectolax. No browser.
Tier 2: Crawl4AI headless Chromium + JsonCss extraction. No tokens.
Tier 3: Crawl4AI LLM extraction against a local Ollama. Slow, VPS only.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field

import httpx

from scrapekit.config import USER_AGENT, Config, load_config
from scrapekit.schema import apply_schema, resolve_urls

_browser_gate: asyncio.Semaphore | None = None


@dataclass
class Page:
    url: str
    tier: int
    status: int = 0
    final_url: str = ""
    html: str = ""
    markdown: str = ""
    rows: list[dict] | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 400


# ---------------------------------------------------------------- tier 1

def tier1_fetch(url: str, schema: dict | None = None, cfg: Config | None = None) -> Page:
    cfg = cfg or load_config()
    page = Page(url=url, tier=1)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
    try:
        with httpx.Client(follow_redirects=True, timeout=cfg.timeout_seconds, headers=headers) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        page.error = f"{type(exc).__name__}: {exc}"
        return page
    page.status = resp.status_code
    page.final_url = str(resp.url)
    page.html = resp.text
    if schema:
        page.rows = apply_schema(page.html, schema, base_url=page.final_url)
    return page


async def tier1_fetch_async(client: httpx.AsyncClient, url: str, schema: dict | None = None) -> Page:
    page = Page(url=url, tier=1)
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        page.error = f"{type(exc).__name__}: {exc}"
        return page
    page.status = resp.status_code
    page.final_url = str(resp.url)
    page.html = resp.text
    if schema:
        page.rows = apply_schema(page.html, schema, base_url=page.final_url)
    return page


def html_to_markdown(html: str, base_url: str = "") -> str:
    """Markdown from raw HTML using Crawl4AI's generator. No browser involved."""
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    result = DefaultMarkdownGenerator().generate_markdown(input_html=html, base_url=base_url)
    return getattr(result, "raw_markdown", None) or str(result)


# ---------------------------------------------------------------- tier 2

def tier2_render(url: str, schema: dict | None = None, wait_for: str | None = None, cfg: Config | None = None) -> Page:
    return asyncio.run(tier2_render_async(url, schema=schema, wait_for=wait_for, cfg=cfg))


async def tier2_render_async(url: str, schema: dict | None = None, wait_for: str | None = None, cfg: Config | None = None, crawler=None) -> Page:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, JsonCssExtractionStrategy

    cfg = cfg or load_config()
    page = Page(url=url, tier=2)
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=int(cfg.timeout_seconds * 1000),
        wait_for=wait_for,
        extraction_strategy=JsonCssExtractionStrategy(schema) if schema else None,
    )

    async def _run(c) -> Page:
        result = await c.arun(url=url, config=run_cfg)
        return _page_from_result(page, result, schema)

    if crawler is not None:
        return await _run(crawler)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=USER_AGENT, verbose=False)) as c:
        return await _run(c)


def _page_from_result(page: Page, result, schema: dict | None) -> Page:
    if not result.success:
        page.error = result.error_message or "crawl failed"
        page.status = result.status_code or 0
        return page
    page.status = result.status_code or 200
    page.final_url = getattr(result, "redirected_url", None) or result.url
    page.html = result.html or ""
    md = result.markdown
    page.markdown = getattr(md, "raw_markdown", None) or (str(md) if md else "")
    if schema:
        try:
            rows = json.loads(result.extracted_content) if result.extracted_content else []
        except json.JSONDecodeError:
            rows = []
        page.rows = resolve_urls(rows, page.final_url, schema)
    return page


# ---------------------------------------------------------------- tier 3

def tier3_llm(url: str, schema: dict, instruction: str = "", cfg: Config | None = None) -> Page:
    cfg = cfg or load_config()
    if cfg.llm_provider.startswith("claude/"):
        return tier3_claude(url, schema, instruction=instruction, cfg=cfg)
    return asyncio.run(tier3_llm_async(url, schema, instruction=instruction, cfg=cfg))


# ---- claude/<model>: headless Claude Code on the subscription, no API key, no local CPU.

MAX_MARKDOWN_CHARS = 60_000


def tier3_claude(url: str, schema: dict, instruction: str = "", cfg: Config | None = None) -> Page:
    """Markdown from the cheapest tier that yields real text, then one `claude -p` call."""
    cfg = cfg or load_config()
    source = tier1_fetch(url, cfg=cfg)
    if source.ok:
        source.markdown = html_to_markdown(source.html, source.final_url or url)
    if not source.ok or len(source.markdown.strip()) < 200:
        source = tier2_render(url, cfg=cfg)
    page = Page(url=url, tier=3, status=source.status, final_url=source.final_url, html=source.html, markdown=source.markdown)
    if not source.ok:
        page.error = source.error or f"status {source.status}"
        return page
    names = [f["name"] for f in schema.get("fields", [])]
    prompt = build_claude_prompt(source.markdown[:MAX_MARKDOWN_CHARS], schema, instruction)
    model = cfg.llm_provider.split("/", 1)[1] or "haiku"
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json", "--max-turns", "1", prompt],
            capture_output=True, text=True, timeout=cfg.timeout_seconds * 4,
        )
    except FileNotFoundError:
        page.error = "claude CLI not found on PATH; install Claude Code or set llm_provider to ollama/..."
        return page
    except subprocess.TimeoutExpired:
        page.error = f"claude -p timed out after {cfg.timeout_seconds * 4:.0f}s"
        return page
    if proc.returncode != 0:
        page.error = f"claude -p exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}"
        return page
    try:
        envelope = json.loads(proc.stdout)
        text = envelope.get("result", "") if isinstance(envelope, dict) else ""
    except json.JSONDecodeError:
        text = proc.stdout
    rows = parse_json_array(text)
    page.rows = [{k: r.get(k) for k in names} for r in rows if isinstance(r, dict)]
    return page


def build_claude_prompt(markdown: str, schema: dict, instruction: str = "") -> str:
    fields = "\n".join(
        f"- {f['name']}" + (f": {f['description']}" if f.get("description") else "")
        for f in schema.get("fields", [])
    )
    task = instruction or "Extract every item on the page."
    return (
        f"{task}\n\nReturn ONLY a JSON array of objects, one per item, with exactly these keys "
        f"(use null when a value is absent):\n{fields}\n\nNo prose, no code fence, no tools. "
        f"Page content follows.\n\n<page>\n{markdown}\n</page>"
    )


def parse_json_array(text: str) -> list:
    """Find the JSON array in a model reply, tolerating a code fence or leading prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end < start:
            return []
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def tier3_llm_async(url: str, schema: dict, instruction: str = "", cfg: Config | None = None) -> Page:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, LLMConfig, LLMExtractionStrategy

    cfg = cfg or load_config()
    page = Page(url=url, tier=3)
    names = [f["name"] for f in schema.get("fields", [])]
    json_schema = {
        "type": "object",
        "properties": {n: {"type": "string"} for n in names},
        "required": names,
    }
    field_hints = "; ".join(f"{f['name']}: {f.get('description') or f.get('selector') or ''}".rstrip(": ") for f in schema.get("fields", []))
    strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider=cfg.llm_provider,
            api_token=cfg.llm_api_token or None,
            base_url=cfg.llm_base_url if cfg.llm_provider.startswith("ollama/") else None,
        ),
        schema=json_schema,
        extraction_type="schema",
        # "/no_think" is Qwen3's soft switch; without it the model reasons at length on CPU.
        instruction=(instruction or "Extract every item on the page.") + f" Fields: {field_hints}. Return one object per item. /no_think",
        input_format="markdown",
        extra_args={"temperature": 0, "max_tokens": 4000},
        chunk_token_threshold=2000,
        verbose=False,
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=int(cfg.timeout_seconds * 1000),
        extraction_strategy=strategy,
    )
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=USER_AGENT, verbose=False)) as c:
        result = await c.arun(url=url, config=run_cfg)
    _page_from_result(page, result, None)
    if page.error:
        return page
    try:
        rows = json.loads(result.extracted_content) if result.extracted_content else []
    except json.JSONDecodeError:
        rows = []
    rows = [{k: r.get(k) for k in names} for r in rows if isinstance(r, dict) and not r.get("error")]
    page.rows = rows
    return page


# ---------------------------------------------------------------- dispatch

def fetch_at_tier(url: str, tier: int, schema: dict | None = None, instruction: str = "", wait_for: str | None = None, cfg: Config | None = None, steps: list[str] | None = None) -> Page:
    if tier == 1:
        return tier1_fetch(url, schema=schema, cfg=cfg)
    if tier == 2:
        return tier2_render(url, schema=schema, wait_for=wait_for, cfg=cfg)
    if tier == 3:
        if not schema:
            raise ValueError("tier 3 needs a schema (field names) to extract into")
        return tier3_llm(url, schema, instruction=instruction, cfg=cfg)
    if tier == 4:
        if not schema:
            raise ValueError("tier 4 needs a schema (field names) to extract into")
        from scrapekit.tier4 import tier4_stagehand

        return tier4_stagehand(url, schema, instruction=instruction, steps=steps, cfg=cfg)
    raise ValueError(f"tier {tier} does not exist; tiers are 1-4")
