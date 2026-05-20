#!/usr/bin/env bash
set -e

echo "Helm linting."
helm lint ./helm/
