#!/usr/bin/env bash
# Build a single-file `lly` binary for the current platform via PyInstaller.
# Output: dist/lly
set -euo pipefail

cd "$(dirname "$0")/.."

# When LLY_VERSION is set (CI does this from the git tag), stamp it into
# src/lly/__init__.py so `lly --version` reports the real release version.
if [[ -n "${LLY_VERSION:-}" ]]; then
  echo "Stamping version: ${LLY_VERSION}"
  sed -i.bak "s/^__version__ = .*/__version__ = \"${LLY_VERSION}\"/" src/lly/__init__.py
  rm src/lly/__init__.py.bak
fi

uv sync --group build

uv run pyinstaller \
  --onefile \
  --name lly \
  --collect-all textual \
  --collect-all rich \
  --collect-all pydantic \
  --collect-all zeroconf \
  --noconfirm \
  --clean \
  src/lly/__main__.py

echo
echo "Built dist/lly ($(du -h dist/lly | cut -f1))"
./dist/lly --version
