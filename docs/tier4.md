# Tier 4: Steel + Stagehand (not installed)

Tier 4 is a persistent browser fleet with anti-bot evasion and scripted auth flows. It is
deliberately absent. An agent never picks tier 4. When `sk probe` says `blocked`, or a
target defeats tiers 1 to 3, add a line under **Requests** below and stop.

## Requests

| Date | Target | URL | What failed | Who asked |
|---|---|---|---|---|

## When two or more real targets are listed, install

1. Steel browser on the VPS, one container, memory-capped:
   `docker run -d --name steel --memory=1500m -p 3000:3000 ghcr.io/steel-dev/steel-browser`
   (check the current image name and tag at github.com/steel-dev/steel-browser first).
2. Stagehand via `uv add stagehand` (Python package) and a `tier4_stagehand()` function in
   `tiers.py` that connects to `http://localhost:3000` and runs the target's `steps` list.
3. Add `tier: 4` to `VALID_TIERS` and `steps:` to the target schema. Keep `max_browsers: 1`.
4. Licenses: Steel is Apache 2.0, Stagehand is MIT. Both stay clear of copyleft.

Firecrawl is not the answer here: its core is AGPL-3.0, which is a problem for anything
bundled into the laser suite or Second Seating.
