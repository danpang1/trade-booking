#!/usr/bin/env bash
set -e
set -o pipefail

log () {
  echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

IMAGE_NAME=${IMAGE_NAME:-unknown_image_name}
VERSION=${VERSION:-unknown_image_version}

log "Packaging docker ${IMAGE_NAME}:${VERSION}"
docker build \
  -f docker/Dockerfile \
  -t "${IMAGE_NAME}:${VERSION}" \
  --target test \
  .

log "Running tests"
docker run "${IMAGE_NAME}:${VERSION}"
