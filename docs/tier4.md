# Tier 4: Steel + Stagehand (installed on the laptop, 2026-09-02)

Tier 4 is a stealth browser driven by an agent. Use it only when `sk probe` says `blocked`
or a target needs actions (dismiss a wall, log in, scroll) before the data appears. Every
tier 4 target must carry a `tier4_reason` in its YAML.

## How it is built

- **Steel** (`ghcr.io/steel-dev/steel-browser`, Apache 2.0) runs in Docker, bound to
  `127.0.0.1:3000`, 2 GB memory cap, auto-restart. It gives fingerprinted, ad-blocked Chromium
  sessions with a CDP endpoint. `scripts/steel-up.sh` starts or recreates it.
- **Stagehand 4** (Python, MIT) is a pure CDP client. Its agent runs as a Chrome extension
  inside the browser. The install script mounts that extension into Steel's extensions
  folder; each session is created with `extensions: ["stagehand"]` so Chrome preloads it,
  and `sk` connects with the resulting extension id. Steel also needs
  `CHROME_ARGS=--enable-unsafe-extension-debugging`.
- **The model is `claude -p`.** Stagehand accepts a custom generate callback; `tier4.py` turns
  each request into one headless Claude Code call (`--model haiku`, `--max-turns 1`) and
  hands the JSON back. No API key. Roughly 12 s per model call, two calls per extraction.

## Using it

```bash
sk probe URL                                   # "blocked" is the trigger
sk extract URL --tier 4 --fields "title,price" \
   --instruction "Extract every listing." --step "close the cookie banner"
sk save-target NAME --note "Cloudflare managed challenge on every page"
```

For tier 4 the CSS selectors in the schema are ignored; only field names and
`description`s reach the model. `steps` are natural-language actions run before extraction.

## Limits

- Laptop only. The VPS is the fleadays production box; a 2 GB stealth browser plus per-page
  model calls do not belong there. `sk remote run` of a tier 4 target will fail on the VPS
  with "Steel is not answering".
- Self-hosted Steel does not solve CAPTCHAs. A page that demands a solved CAPTCHA is out of
  scope; note it below and stop.
- Each page costs two Haiku calls through the subscription. Keep `delay_seconds` at 2+.

## Requests and outcomes

| Date | Target | URL | What failed at tiers 1-3 | Tier 4 result |
|---|---|---|---|---|
| 2026-09-02 | smoke | https://quotes.toscrape.com/js/ | nothing (validation run) | 10/10 rows, 27 s |
| 2026-09-02 | smoke | https://nowsecure.nl/ | Cloudflare managed challenge at tier 1 | passed the challenge, page content extracted, 19 s |
| 2026-09-02 | quotes-login (committed target) | https://quotes.toscrape.com/login | login wall before the data | 3 `steps` logged in (header shows Logout), 10/10 rows, 70 s |
