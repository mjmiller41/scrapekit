#!/usr/bin/env bash
# Start (or recreate) the Steel browser container for tier 4. Idempotent.
# Binds to localhost only, 2 GB memory cap, restarts with Docker, and mounts Stagehand's
# browser extension into Steel's extensions folder so sessions can preload it.
set -euo pipefail

cd "$(dirname "$0")/.."
EXT=$(uv run --extra tier4 python -c "from stagehand.extension_assets import extension_directory; print(extension_directory())")
IMAGE="ghcr.io/steel-dev/steel-browser:latest"

if docker inspect steel >/dev/null 2>&1; then
  current=$(docker inspect steel --format '{{range .Mounts}}{{.Source}}{{end}}')
  if [ "$current" = "$EXT" ] && [ "$(docker inspect steel --format '{{.State.Running}}')" = "true" ]; then
    echo "steel already running with the current extension"; exit 0
  fi
  docker rm -f steel >/dev/null
fi

docker run -d --name steel --restart unless-stopped --memory 2g \
  -p 127.0.0.1:3000:3000 \
  -e CHROME_ARGS="--enable-unsafe-extension-debugging" \
  -v "$EXT:/app/api/extensions/stagehand:ro" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  curl -sf localhost:3000/v1/sessions >/dev/null && { echo "steel up at http://localhost:3000"; exit 0; }
  sleep 1
done
echo "steel did not come up; docker logs steel" >&2
exit 1
