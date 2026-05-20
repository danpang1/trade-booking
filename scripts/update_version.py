#!/usr/bin/env python

import os.path
import re
from typing import List, Sequence

SEMANTIC_VERSION_PATTERN = re.compile(r"""
    (0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)
    (?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
    (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?
    (?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?
    """, re.X)


def increment_version(line: str, search_terms: List[str]) -> str:

    is_line_valid = False
    for term in search_terms:
        if re.search(term, line) is not None:
            is_line_valid = True
            break

    if is_line_valid is False:
        return line

    match = re.search(SEMANTIC_VERSION_PATTERN, line)
    version = match.group(0)
    major = match.group(1)
    minor = match.group(2)
    patch = match.group(3)
    label = match.group(4)

    new_patch = str(int(patch) + 1)

    if not label:
        new_ver = f"{major}.{minor}.{new_patch}"
    else:
        new_ver = f"{major}.{minor}.{new_patch}-{label}"

    return line.replace(version, new_ver)


def process_file(file_name: str, search_terms: Sequence[str]):
    if not os.path.isfile(file_name):
        return

    with open(file_name, "rt") as fin:
        lines = fin.readlines()

    with open(file_name, "wt") as fout:
        for line in lines:
            line = increment_version(line, search_terms)
            fout.write(line)


process_file("version.yml", [r"^version\: \"?"])
process_file("helm/Chart.yaml", [r"^version\: \"?", r"^appVersion\: \"?"])

# Let's avoid rebuilding image layers when we do not publish other artifacts,
# other than images.
# process_file("pyproject.toml", [r"^version \= \"?"])
# process_file("package.json", [r"^ *\"version\" *\: *\"?"])
# process_file("setup.py", [r"^ *version *\= *\"?"])
