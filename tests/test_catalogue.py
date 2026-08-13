#!/usr/bin/env python3
"""The executable gate for tests/CATALOGUE.md.

A test map that drifts from the suite is worse than no map — it describes
coverage that may not exist and hides coverage that does. These tests make
drift impossible: add a test module without cataloguing it, or catalogue one
that isn't there, and the suite goes red.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalogue


def test_every_module_is_catalogued():
    """A new test module must be added to the map in the same change."""
    listed = set(catalogue.surface_of())
    on_disk = set(catalogue.test_modules_on_disk())

    missing = sorted(on_disk - listed)
    assert not missing, (
        "these test modules are missing from tests/CATALOGUE.md: "
        + ", ".join(missing)
    )


def test_catalogue_lists_no_phantom_modules():
    """The map must not describe tests that do not exist."""
    listed = set(catalogue.surface_of())
    on_disk = set(catalogue.test_modules_on_disk())

    phantom = sorted(listed - on_disk)
    assert not phantom, (
        "tests/CATALOGUE.md lists modules that are not on disk: "
        + ", ".join(phantom)
    )


def test_each_module_has_exactly_one_surface():
    """Two surfaces means `pytest -m <tag>` would run it twice and the blast
    radius claim in the table would be meaningless."""
    duplicated = {
        module: surfaces
        for module, surfaces in catalogue.surface_of().items()
        if len(surfaces) > 1
    }
    assert not duplicated, (
        "these modules are listed under more than one surface: "
        + "; ".join(f"{m} -> {', '.join(s)}" for m, s in sorted(duplicated.items()))
    )


def test_every_declared_surface_has_modules():
    """A tag in the summary table with nothing behind it is a lie about what
    `pytest -m <tag>` will run."""
    parsed = catalogue.parse()
    empty = sorted(tag for tag in catalogue.declared_surfaces()
                   if not parsed.get(tag))
    assert not empty, (
        "these surfaces are documented in the table but have no modules: "
        + ", ".join(empty)
    )


def test_every_used_surface_is_documented_in_the_table():
    """A section heading with no table row has no stated blast radius, which is
    the one thing this catalogue is organized around."""
    documented = set(catalogue.declared_surfaces())
    used = set(catalogue.parse())

    undocumented = sorted(used - documented)
    assert not undocumented, (
        "these surfaces have sections but no row in the summary table: "
        + ", ".join(undocumented)
    )


def test_markers_are_applied_to_this_module(request):
    """The mapping in the catalogue is what conftest turns into markers.

    If this fails, `pytest -m <surface>` silently selects nothing and every
    'How to run' cell in the table is wrong.
    """
    own_surfaces = catalogue.surface_of().get("test_catalogue.py", [])
    assert own_surfaces, "test_catalogue.py is not catalogued"
    assert request.node.get_closest_marker(own_surfaces[0]) is not None, (
        f"expected this test to carry the '{own_surfaces[0]}' marker"
    )
