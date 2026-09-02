# scrapekit

Tiered, target-driven scraping. Cheapest tier first; move up only when a page forces it.

| Tier | What | When |
|---|---|---|
| 1 | httpx + selectolax, CSS schema | Default. Server-rendered HTML. Milliseconds. |
| 2 | Crawl4AI headless Chromium, same CSS schema | Probe says JS shell, or tier 1 fields come back empty. |
| 3 | Crawl4AI LLM extraction on local Ollama (`qwen3:4b`) | DOM cannot be described with CSS. VPS only. Slow. |
| 4 | Steel + Stagehand | Not installed. See `docs/tier4.md`. |

Licenses in the stack: httpx BSD, selectolax MIT, Crawl4AI Apache 2.0, Playwright Apache 2.0.

## Install

```bash
uv tool install --editable .          # gives you `sk`
uv run python -m playwright install chromium   # tier 2 (laptop already has it)
```

VPS: `ssh hostinger-vps 'bash -s' < scripts/vps-install.sh`. Idempotent. It also writes the
shared-box caps to `~/.config/scrapekit/config.yaml` there.

## Three ways to use it

**One-off, from any agent session:**

```bash
sk probe URL
sk fetch URL                       # markdown, capped at 200 lines (--full, --html, --json)
sk extract URL --base "div.item" --fields "title=h2,price=.price,url=a@href"
sk save-target NAME --key url      # promote the last extract to targets/NAME.yaml
```

**Repeated targets** (`targets/NAME.yaml`, see `targets/_example.yaml`):

```bash
sk extract URL --target NAME       # dry-run one page, prints fill rates
sk run NAME --dry-run              # every url, nothing written
sk remote run NAME                 # push targets to the VPS, run there, pull data back
sk targets
```

**From another project:**

```python
from scrapekit import extract, fetch, run
page = extract("https://...", schema, tier=1)   # page.rows
```

or read `~/.local/share/scrapekit/NAME/DATE.jsonl` and `scrapekit.db` (tables `items`, `runs`).

## Escalation rule

`sk extract` exits 3 when a field fills under 50% or the base selector matched nothing.
Fix the selector first. If the markup is not in the HTML, raise `tier` by exactly one.
Tier 3 needs `llm_instruction` in the YAML. Tier 4 is never chosen by an agent.

## Paths and caps

`sk where` prints them. Data: `$SCRAPEKIT_DATA` (default `~/.local/share/scrapekit`).
Targets: `$SCRAPEKIT_TARGETS` (default `targets/` in this checkout). Per-machine caps and
the Ollama endpoint: `~/.config/scrapekit/config.yaml`.

On the VPS `low_priority: true` makes every run renice itself and use idle I/O, one run at
a time (file lock), one browser, tier 3 serial. Target values above the caps are clamped.

## Tests

```bash
uv run pytest             # fixtures only
uv run pytest -m live     # books.toscrape.com (tier 1) and quotes.toscrape.com/js (tier 2)
```

## Agent skill

`skills/scrape-data/SKILL.md` is symlinked into `~/.claude/skills/` and `~/.pi/agent/skills/`.
