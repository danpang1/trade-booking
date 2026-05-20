#!/usr/bin/env bash
set -e

python3 -m venv .venv-test

. .venv-test/bin/activate

pip install --upgrade flake8

# Enforce style consistency across Python projects https://flake8.pycqa.org/en/latest/manpage.html.
flake8 \
	-v \
	--show-source \
	--statistics \
	--exclude ".venv**" \
	--max-line-length=88 \
	--ignore=E203,W503,E501,F841,F401,E722,F541,F811,F811,E262,C901 \
	.
