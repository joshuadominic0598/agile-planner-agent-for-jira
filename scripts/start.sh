#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker is required. Install Docker Desktop (or Docker Engine with Compose), then run make start.' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo 'Docker is not running. Start Docker Desktop / Docker Engine, then run make start.' >&2
  exit 1
fi
mkdir -p resources/app resources/mongodb resources/mongodb-config
fingerprint=$(sh scripts/image-fingerprint.sh)
image=$(docker compose config --images app | sed '/^mongo:/d' | head -n 1)
image_id=$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null || true)
expected=$(printf '%s\n%s' "$fingerprint" "$image_id")
previous=$(cat resources/app/.image-build 2>/dev/null || true)
if [ "${REBUILD:-0}" = "1" ] || [ -z "$image_id" ] || [ "$previous" != "$expected" ]; then
  docker compose build app
  image_id=$(docker image inspect --format '{{.Id}}' "$image")
  printf '%s\n%s\n' "$fingerprint" "$image_id" > resources/app/.image-build
else
  echo 'Using the current application image.'
fi
if [ "${BUILD_ONLY:-0}" = "1" ]; then
  exit 0
fi
docker compose up --no-build -d --wait --wait-timeout 120
address=$(docker compose port app 8000)
url="http://localhost:${address##*:}"
echo "AgilePlanner is ready: $url"
if [ "${OPEN_BROWSER:-1}" = "1" ]; then
  if command -v open >/dev/null 2>&1; then
    open "$url" || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
fi
