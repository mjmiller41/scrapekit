#!/usr/bin/env bash
# Idempotent bootstrap for the crawl box. Run from the laptop:
#   ssh hostinger-vps 'bash -s' < scripts/vps-install.sh
# Chromium's system libraries need root once; the script prints the command if sudo fails.
set -euo pipefail

REPO_URL="${SCRAPEKIT_REPO_URL:-https://github.com/mjmiller41/scrapekit.git}"
REPO_DIR="$HOME/Code/scrapekit"
CONF_DIR="$HOME/.config/scrapekit"
export PATH="$HOME/.local/bin:$PATH"

echo "== uv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version

echo "== repo"
mkdir -p "$HOME/Code"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$REPO_DIR"
fi

echo "== install sk"
cd "$REPO_DIR"
uv python install 3.12 >/dev/null
uv tool install --editable --reinstall --python 3.12 . >/dev/null
sk where

echo "== chromium"
uv run --python 3.12 python -m playwright install chromium >/dev/null
if ! uv run --python 3.12 python -c "
import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig
async def m():
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as c:
        r = await c.arun('raw://<html><body><p>ok</p></body></html>')
        assert r.success, r.error_message
asyncio.run(m())
" 2>/dev/null; then
  if sudo -n true 2>/dev/null; then
    sudo "$HOME/.local/bin/uv" run --python 3.12 python -m playwright install-deps chromium
  else
    echo "!! Chromium needs system libraries. Run once as root, then rerun this script:"
    echo "   sudo $HOME/.local/bin/uv run --project $REPO_DIR --python 3.12 python -m playwright install-deps chromium"
    exit 2
  fi
fi

echo "== config (shared box caps)"
mkdir -p "$CONF_DIR" "$HOME/.local/share/scrapekit"
if [ ! -f "$CONF_DIR/config.yaml" ]; then
  cat > "$CONF_DIR/config.yaml" <<'EOF'
# Caps for the shared VPS. Target values above these are clamped.
max_concurrency: 2
max_browsers: 1
tier3_serial: true
low_priority: true      # sk run renices itself to 15 and ionice idle
# Tier 3 model. claude/<model> = headless Claude Code on the subscription: seconds, no CPU.
# ollama/qwen3:4b is available but measured ~28 tok/s in, ~14 out here; one small page did
# not finish in 5 minutes and pegged both cores. Do not use it on this box.
llm_provider: claude/haiku
timeout_seconds: 30
EOF
fi

echo "== claude (tier 3)"
command -v claude >/dev/null && claude --version || echo "!! claude CLI missing: tier 3 needs Claude Code installed and logged in"

echo "== smoke"
sk probe https://books.toscrape.com/ | grep -E '^tier'
sk probe https://quotes.toscrape.com/js/ | grep -E '^tier'
echo "done"
