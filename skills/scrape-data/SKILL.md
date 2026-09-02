---
name: scrape-data
description: Pull structured data from web pages with the tiered `sk` tool (httpx → Crawl4AI browser → headless Claude). Use for "scrape", "pull the listings from", "get every X on this site", "keep collecting", or when a project needs a repeatable data feed. Not for one-off "what does this page say" questions where reading it once is enough.
---

# scrape-data

`sk` is installed on this machine and on the VPS (`hostinger-vps`). It escalates through
tiers only when a page forces it. Cheapest first, always.

| Tier | Tool | Cost |
|---|---|---|
| 1 | httpx + CSS selectors | milliseconds, no browser |
| 2 | Crawl4AI headless Chromium, same CSS schema | seconds |
| 3 | headless Claude (`claude -p`, Haiku) over the page markdown | seconds, needs a written justification |
| 4 | not installed | write the need to `docs/tier4.md` and stop |

Run `sk where` once if you need the data or targets directory.

## Process

**0. One-off ask** ("what are the prices on this page", "list the talks on this schedule"):

```bash
sk extract URL --base "div.item" --fields "title=h2,price=.price,url=a@href"
```

Tier is probed automatically. Answer from the JSON and stop. No target file, no VPS.
If the user says "keep doing this" or the same ask comes back, promote it:

```bash
sk save-target NAME --key url --note "why this exists"
```

then continue at step 5.

**1. Existing target?** `sk targets`. If the name is there: `sk remote run NAME`, report, stop.

**2. Probe.** `sk probe URL`. Take the recommended tier. `blocked` means stop and log to
`docs/tier4.md`.

**3. Look at the page.** `sk fetch URL --tier N` (markdown, capped at 200 lines) or
`sk fetch URL --html --tier N` when you need the real selectors. Write a schema: a
`baseSelector` that matches one item, and one CSS selector per field.

**4. Dry-run until every field fills.**

```bash
sk extract URL --base "SELECTOR" --fields "..."      # or --schema file.yaml
```

Exit code 3 means a field is under 50% or nothing matched. Fix the selector first. Only if
the markup is genuinely not in the HTML, raise the tier by exactly one (`--tier 2`) and
repeat. Tier 3 (`--tier 3 --instruction "..."`) is for DOMs that cannot be described with
CSS; it needs the instruction. It costs a model call per page, so never use it where a
selector would do.

**5. Save and run.** `sk save-target NAME --key FIELD` writes `targets/NAME.yaml`. Edit
`urls` or `url_template` + `page_range` and `delay_seconds`. Commit it. Then:

```bash
sk remote run NAME
```

Report: rows, new, changed, errors, and the JSONL path printed as `local copy`.

## Rules

- Never run a multi-page target from the laptop. `sk run` locally is for `--dry-run` only.
  The VPS has the clean IP and the resource caps.
- One tier up at a time. Never jump to tier 3 because it "might work".
- Tier 3 needs `llm_instruction` in the YAML saying what to extract and why CSS failed.
- Keep `delay_seconds` at 1 or higher on anything that is not a demo site.
- Data lives in `~/.local/share/scrapekit/` (`scrapekit.db` + `NAME/DATE.jsonl`). Other
  projects read that; they do not import targets.
- `sk fetch` output is capped at 200 lines. Use `--full` only when you must.
