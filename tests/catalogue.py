"""
Read ``tests/CATALOGUE.md`` as data.

The catalogue is the single source of truth for which surface each test module
belongs to. Two things consume it:

* ``tests/conftest.py`` applies the surface as a pytest marker, so
  ``pytest -m memory`` works without a tag in any test file.
* ``tests/test_catalogue.py`` fails the suite if the catalogue and the files on
  disk disagree.

Keeping the mapping in the document means the document cannot rot: it is not a
description of the suite, it *is* the suite's index.
"""

import re
from pathlib import Path
from typing import Dict, List

CATALOGUE_PATH = Path(__file__).resolve().parent / "CATALOGUE.md"
TESTS_DIR = Path(__file__).resolve().parent

#: Surface headings look like "## @memory — writing into surfaces …".
_SURFACE_RE = re.compile(r"^##\s+@([a-z][a-z0-9_-]*)\s")

#: Module entries look like "# test_native_memory.py" inside a gherkin block.
_MODULE_RE = re.compile(r"^#\s+(test_[A-Za-z0-9_]+\.py)\b")

#: The surface table lists every tag with a `pytest -m <tag>` invocation.
_TABLE_TAG_RE = re.compile(r"^\|\s*`@([a-z][a-z0-9_-]*)`\s*\|")


def _read() -> str:
    return CATALOGUE_PATH.read_text(encoding="utf-8")


def declared_surfaces() -> List[str]:
    """Surface tags named in the summary table, in table order."""
    return [m.group(1) for line in _read().splitlines()
            for m in [_TABLE_TAG_RE.match(line)] if m]


def parse() -> Dict[str, List[str]]:
    """Return ``{surface: [module filename, ...]}`` in document order.

    A module listed under two surfaces appears under both; the gate is what
    rejects that, not the parser. The parser reports what the document says.
    """
    surfaces: Dict[str, List[str]] = {}
    current = None

    for line in _read().splitlines():
        heading = _SURFACE_RE.match(line)
        if heading:
            current = heading.group(1)
            surfaces.setdefault(current, [])
            continue
        module = _MODULE_RE.match(line)
        if module and current:
            surfaces[current].append(module.group(1))

    return surfaces


def surface_of() -> Dict[str, List[str]]:
    """Return ``{module filename: [surface, ...]}``.

    A well-formed catalogue yields exactly one surface per module. The list
    shape is deliberate: the gate needs to *see* a double listing to report it.
    """
    owners: Dict[str, List[str]] = {}
    for surface, modules in parse().items():
        for module in modules:
            owners.setdefault(module, []).append(surface)
    return owners


def test_modules_on_disk() -> List[str]:
    """Every test module the suite actually contains."""
    return sorted(p.name for p in TESTS_DIR.glob("test_*.py"))
