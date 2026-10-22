#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
{
  find backend/app frontend/src resources/demo -type f ! -name '*.pyc' -exec cksum {} +
  if [ -d frontend/public ]; then
    find frontend/public -type f -exec cksum {} +
  fi
  cksum Dockerfile backend/requirements.txt frontend/package.json frontend/pnpm-lock.yaml frontend/index.html frontend/operations.html frontend/tsconfig*.json frontend/vite.config.ts
} | LC_ALL=C sort | cksum
