"""Library entry points. The CLI is a thin layer over these."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time

import httpx

from scrapekit.config import USER_AGENT, Config, load_config
from scrapekit.probe import Probe, probe as _probe
from scrapekit.schema import fill_rates
from scrapekit.store import RunSummary, connect, log_run, now_iso, run_lock, upsert, write_jsonl
from scrapekit.targets import Target, load_target
from scrapekit.tiers import Page, fetch_at_tier, html_to_markdown, tier1_fetch_async, tier2_render_async


def probe(url: str) -> Probe:
    return _probe(url)


def fetch(url: str, tier: int | None = None, cfg: Config | None = None) -> Page:
    """Get a page. With tier=None, probe first and use the recommended tier (1 or 2)."""
    cfg = cfg or load_config()
    if tier is None:
        p = _probe(url)
        tier = p.recommended_tier if isinstance(p.recommended_tier, int) else 2
    page = fetch_at_tier(url, tier, cfg=cfg)
    if page.ok and not page.markdown and page.html:
        page.markdown = html_to_markdown(page.html, page.final_url or url)
    return page


def extract(url: str, schema: dict, tier: int | None = None, instruction: str = "", wait_for: str | None = None, cfg: Config | None = None, steps: list[str] | None = None) -> Page:
    """Apply a schema to one URL. Page.rows holds the result."""
    cfg = cfg or load_config()
    if tier is None:
        p = _probe(url)
        tier = p.recommended_tier if isinstance(p.recommended_tier, int) else 2
    if tier >= 2:
        _lower_priority(cfg)
    return fetch_at_tier(url, tier, schema=schema, instruction=instruction, wait_for=wait_for, cfg=cfg, steps=steps)


def run(target_name: str, dry_run: bool = False, no_wait: bool = False, cfg: Config | None = None) -> RunSummary:
    cfg = cfg or load_config()
    target = load_target(target_name)
    _lower_priority(cfg)
    with run_lock(wait=not no_wait):
        return _run_target(target, cfg, dry_run=dry_run)


def _lower_priority(cfg: Config) -> None:
    if not cfg.low_priority:
        return
    try:
        os.nice(15)
    except OSError:
        pass
    subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())], check=False, capture_output=True)


def _run_target(target: Target, cfg: Config, dry_run: bool) -> RunSummary:
    summary = RunSummary(target=target.name, tier=target.tier, started=now_iso())
    urls = target.all_urls()
    summary.urls = len(urls)
    concurrency = max(1, min(target.concurrency, cfg.max_concurrency))

    if target.tier == 1:
        pages = asyncio.run(_tier1_many(urls, target, cfg, concurrency))
    elif target.tier == 2:
        pages = asyncio.run(_tier2_many(urls, target, cfg))
    else:
        # tiers 3 and 4 are always serial: one model call chain at a time.
        pages = [fetch_at_tier(u, target.tier, schema=target.schema, instruction=target.llm_instruction, cfg=cfg, steps=target.steps) for u in urls]

    rows: list[dict] = []
    for page in pages:
        if page.error or not page.ok:
            summary.errors.append(f"{page.url}: {page.error or f'status {page.status}'}")
            continue
        rows.extend(page.rows or [])
    summary.rows = len(rows)
    summary.fill_rates = fill_rates(rows, target.schema)

    if not dry_run and rows:
        conn = connect()
        try:
            summary.new, summary.changed = upsert(target.name, rows, target.key, conn)
        finally:
            conn.close()
        summary.output = str(write_jsonl(target.name, rows))
    summary.finished = now_iso()
    if not dry_run:
        log_run(summary)
    return summary


async def _tier1_many(urls: list[str], target: Target, cfg: Config, concurrency: int) -> list[Page]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=cfg.timeout_seconds, headers=headers) as client:
        async def one(u: str) -> Page:
            async with sem:
                page = await tier1_fetch_async(client, u, schema=target.schema)
                await asyncio.sleep(target.delay_seconds)
                return page
        return list(await asyncio.gather(*(one(u) for u in urls)))


async def _tier2_many(urls: list[str], target: Target, cfg: Config) -> list[Page]:
    """One browser, pages in sequence. `max_browsers` is 1 by design on the shared box."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig

    pages: list[Page] = []
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=USER_AGENT, verbose=False)) as crawler:
        for u in urls:
            pages.append(await tier2_render_async(u, schema=target.schema, wait_for=target.wait_for, cfg=cfg, crawler=crawler))
            time.sleep(target.delay_seconds)
    return pages
