#!/usr/bin/env bash
set -e
set -o pipefail

log () {
  echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

log "Packaging helm"
helm package \
  ./helm \
  --version "0.0.1-dev" \
  --debug
