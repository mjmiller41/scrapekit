# scrapekit

Tiered, target-driven scraping. Cheapest tier first; move up only when a page forces it.

| Tier | What | When |
|---|---|---|
| 1 | httpx + selectolax, CSS schema | Default. Server-rendered HTML. Milliseconds. |
| 2 | Crawl4AI headless Chromium, same CSS schema | Probe says JS shell, or tier 1 fields come back empty. |
| 3 | LLM extraction. Default `claude/haiku`: headless Claude Code (`claude -p`) on the subscription. Or any Crawl4AI/LiteLLM provider such as `ollama/qwen3:4b`. | DOM cannot be described with CSS. Seconds with Claude; minutes on CPU Ollama. |
| 4 | Steel stealth browser (Docker) driven by Stagehand, model via `claude -p` | Probe says `blocked`, or the data needs actions first. Laptop only. `docs/tier4.md`. |

Licenses in the stack: httpx BSD, selectolax MIT, Crawl4AI Apache 2.0, Playwright Apache 2.0.

## Install

```bash
uv tool install --editable .          # gives you `sk`
uv run python -m playwright install chromium   # tier 2 (laptop already has it)
uv tool install --editable '.[tier4]' && scripts/steel-up.sh   # tier 4, laptop only
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
Tier 3 needs `llm_instruction` in the YAML. Tier 4 needs `tier4_reason` and is reached only
from a `blocked` probe or a page that needs `steps` before the data exists.

## Paths and caps

`sk where` prints them. Data: `$SCRAPEKIT_DATA` (default `~/.local/share/scrapekit`).
Targets: `$SCRAPEKIT_TARGETS` (default `targets/` in this checkout). Per-machine caps and
the Ollama endpoint: `~/.config/scrapekit/config.yaml`.

On the VPS `low_priority: true` makes every run renice itself and use idle I/O, one run at
a time (file lock), one browser, tier 3 serial. Target values above the caps are clamped.

## Tier 3 models

`claude/<model>` (default `claude/haiku`) fetches the page at the cheapest tier that yields
text, converts it to markdown, and makes one `claude -p --max-turns 1` call. Needs Claude Code
installed and logged in on that machine; no API key, no local CPU. Measured on the VPS: about
two seconds per call.

`ollama/qwen3:4b` is wired but measured on the VPS (2 vCPU, no GPU) at about 28 tokens/s in
and 14 out: one 10-item page did not finish in 5 minutes and pinned both cores of the
fleadays production box. Leave it off there.

## Tests

```bash
uv run pytest             # fixtures only
uv run pytest -m live     # books.toscrape.com (tier 1) and quotes.toscrape.com/js (tier 2)
```

## Agent skill

`skills/scrape-data/SKILL.md` is symlinked into `~/.claude/skills/` and `~/.pi/agent/skills/`.
