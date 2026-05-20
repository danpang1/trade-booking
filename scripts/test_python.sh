#!/usr/bin/env bash
set -e

python3 -m venv .venv-test

. .venv-test/bin/activate

pip install --upgrade pytest

# pip install --upgrade poetry
# poetry install --no-interaction --no-root;

CI=1 python -m pytest --tb=short -vv
