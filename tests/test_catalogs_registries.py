"""Catalog declarations: ``algorithms/catalogs/``.

This package is declaration-only — band tables, colour transforms, VizieR IDs.
The tests here guard three things:

* the **no-network guarantee**: importing ``catalogs`` must not pull in
  astroquery or open anything. This is what lets filter matching and the whole
  zero-point solve run with no network stack installed;
* the **two-registry divergence**: ``CATALOGS`` (11 catalogs) and
  ``CATALOG_OPTIONS`` (APASS + PanSTARRS) disagree deliberately, and merging
  them would silently change which reference band a narrowband image calibrates
  against (``algorithms/catalogs/EXTRACTION.md`` §4);
* the **colour transforms themselves**, which are numeric calibration behaviour
  copied verbatim from upstream, not style.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from algorithms.catalogs import (
    CATALOG_OPTIONS,
    CATALOGS,
    NARROWBAND_FILTER_LOOKUP,
    SIMBAD_OBJECT_TYPES,
    Catalog,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Every catalog Kepler declares, and the VizieR table behind it. Pinned because
#: a changed table ID silently repoints a query at different photometry.
EXPECTED_CATALOGS = {
    "APASS": "II/336",
    "PanSTARRS": "II/349",
    "SDSS": None,          # queried through SkyServer SQL, not VizieR
    "SkyMapper": "II/358/smss",
    "Landolt": "II/183A",
    "Stetson": "J/MNRAS/485/3042/table4",
    "2MASS": "II/246",
    "Tycho": "I/259",
    "UCAC": "I/340",
    "USNO": "I/284",
    "VSX": "B/vsx/vsx",
}

#: Registry keys whose ``name`` attribute differs from the key. Callers pass the
#: key, so the mismatch only traps code that reads ``catalog.name`` and tries to
#: look it up again.
NAME_MISMATCHES = {"Stetson": "StetsonGlobs", "Tycho": "Tycho2",
                   "UCAC": "UCAC5", "USNO": "USNOB1"}


# ---------------------------------------------------------------------------
# The no-network guarantee
# ---------------------------------------------------------------------------

def test_importing_catalogs_does_not_import_astroquery():
    """``import algorithms.catalogs`` must stay free of any network stack.

    Run in a subprocess because by the time this test executes, another test may
    already have imported astroquery — checking ``sys.modules`` in-process would
    be a false positive either way.
    """
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, algorithms.catalogs; "
         "bad = sorted(m for m in sys.modules "
         "             if m.split('.')[0] in {'astroquery', 'requests', 'pyvo', 'urllib3'}); "
         "assert not bad, bad"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr


def test_catalogs_never_imports_query():
    """The dependency runs one way: ``query`` imports ``catalogs``, never back.

    That direction is what keeps filter matching and the zero-point solve
    runnable with no network stack installed. A cycle here would also be an
    import-time failure waiting to happen.
    """
    import re

    # Import statements only — every module here mentions ``algorithms/query/`` in prose.
    pattern = re.compile(r"^\s*(?:from\s+(?:algorithms\.)?query[\s.]|import\s+(?:algorithms\.)?query\b)", re.MULTILINE)
    for source in (REPO_ROOT / "algorithms" / "catalogs").glob("*.py"):
        assert not pattern.search(source.read_text()), source.name


def test_bare_declarations_refuse_to_query():
    """A plugin knows what it contains, not how to reach it.

    All three query methods raise with a pointer to ``algorithms.query.registry``. This is
    the boundary that makes the declarations importable without astroquery.
    """
    catalog = CATALOGS["APASS"]
    for method, args in (
        ("query_objects", (["M31"],)),
        ("query_box", (1.0, 2.0, 10.0)),
        ("query_circ", (1.0, 2.0, 10.0)),
        ("table_to_sources", ([],)),
    ):
        with pytest.raises(NotImplementedError, match="query.registry"):
            getattr(Catalog, method)(catalog, *args)


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

def test_registry_contains_exactly_the_eleven_declared_catalogs():
    assert set(CATALOGS) == set(EXPECTED_CATALOGS)
    assert len(CATALOGS) == 11


@pytest.mark.parametrize("name,vizier_id", sorted(EXPECTED_CATALOGS.items()))
def test_vizier_table_ids_are_pinned(name, vizier_id):
    """A changed table ID repoints the query at different photometry."""
    assert getattr(CATALOGS[name], "vizier_catalog", None) == vizier_id


@pytest.mark.parametrize("name", sorted(EXPECTED_CATALOGS))
def test_every_catalog_declares_a_name_and_a_band_table(name):
    catalog = CATALOGS[name]
    assert catalog.name is not None
    assert catalog.display_name
    assert getattr(catalog, "mags", None), f"{name} declares no bands"


@pytest.mark.parametrize("name", sorted(EXPECTED_CATALOGS))
def test_registry_key_matches_the_declared_name_except_where_pinned(name):
    """Four catalogs are registered under a key differing from ``name``.

    Callers pass the *key*, so the mismatch only traps code that reads
    ``catalog.name`` and looks it up again — and ``CatalogSource.catalog_name``
    is populated from ``name``, so a source coming back from Stetson reports a
    catalog string that matches no registry key.
    """
    assert CATALOGS[name].name == NAME_MISMATCHES.get(name, name)


@pytest.mark.parametrize("name", sorted(set(EXPECTED_CATALOGS) - {"VSX"}))
def test_band_tables_map_to_column_name_lists(name):
    """``mags`` is ``{band: [mag_column, error_column]}``; the error is optional.

    An empty list is meaningful: the band exists but is synthesised by a
    ``table_to_sources`` override rather than read from a column. VSX is
    excluded — it uses a different convention, pinned separately below.
    """
    for band, columns in CATALOGS[name].mags.items():
        assert isinstance(band, str) and band
        assert isinstance(columns, list), f"{name}.{band} is {type(columns).__name__}"
        assert len(columns) <= 2
        assert all(isinstance(c, str) for c in columns)


def test_vsx_declares_its_bands_as_empty_strings_not_empty_lists():
    """PRESERVED QUIRK: VSX's ``mags`` values are ``''``, not ``[]``.

    Every other catalog maps a band to a list of column names. VSX maps all 35
    of its bands to the empty *string*. Both are falsy, and the readers that ask
    "does this catalog have band X" go through ``set(catalog.mags)``, which only
    looks at keys — which is why the divergence has never mattered and is
    preserved rather than normalised.

    It would matter to anything that indexes the value. This test exists so a
    future reader who writes ``columns[0]`` against ``catalog.mags`` finds out
    here rather than at query time: VSX is queried only for positional
    variable-star rejection, and ``_filter_variable_stars`` swallows exceptions,
    so such a bug would silently disable that filtering instead of raising.
    """
    mags = CATALOGS["VSX"].mags
    assert len(mags) > 30
    assert set(mags.values()) == {""}
    assert all(isinstance(v, str) for v in mags.values())


def test_landolt_synthesises_bands_with_no_backing_column():
    """UBVRI come out of the colour transform, so their column lists are empty."""
    mags = CATALOGS["Landolt"].mags
    assert mags["V"], "V is read straight from the table"
    for synthesised in ("B", "U", "R", "I"):
        assert mags[synthesised] == [], synthesised


# ---------------------------------------------------------------------------
# The two-registry divergence
# ---------------------------------------------------------------------------

def test_catalog_options_is_a_two_catalog_subset():
    assert set(CATALOG_OPTIONS) == {"APASS", "PanSTARRS"}
    assert set(CATALOG_OPTIONS) < set(CATALOGS)


def test_the_two_apass_declarations_are_different_classes():
    """Deliberate: upstream had two parallel plugin packages that had drifted.

    Preserving the drift is the whole reason ``catalog_options.py`` redefines
    APASS and PanSTARRS instead of importing them.
    """
    assert type(CATALOGS["APASS"]) is not type(CATALOG_OPTIONS["APASS"])
    assert type(CATALOGS["PanSTARRS"]) is not type(CATALOG_OPTIONS["PanSTARRS"])


def test_narrowband_aliases_exist_only_in_catalog_options():
    """The load-bearing difference, stated as an assertion.

    ``resolve_ref_mag_for_filter`` reads ``CATALOG_OPTIONS``. If the registries
    were merged, an ``H_alpha`` frame would stop resolving to r' and fall
    through to the preferred-band fallback — calibrating against V instead, with
    no error raised.
    """
    options_lookup = CATALOG_OPTIONS["APASS"].filter_lookup
    catalogs_lookup = CATALOGS["APASS"].filter_lookup

    for alias in ("H_alpha", "H_beta"):
        assert alias in options_lookup
        assert alias not in catalogs_lookup

    # The reverse direction also differs: CATALOGS carries SII, CATALOG_OPTIONS
    # gets it via NARROWBAND_FILTER_LOOKUP, and both resolve to r'.
    assert catalogs_lookup["SII"] == "rprime"
    assert options_lookup["SII"] == "rprime"


def test_narrowband_lookup_maps_hydrogen_to_r_and_oxygen_to_g():
    assert NARROWBAND_FILTER_LOOKUP == {
        "SII": "rprime",
        "Halpha": "rprime",
        "H_alpha": "rprime",
        "OIII": "gprime",
        "Hbeta": "gprime",
        "H_beta": "gprime",
    }


def test_halpha_resolves_differently_between_the_two_registries():
    """Not just a missing key — the same key resolves to different things.

    ``CATALOGS['APASS']`` maps ``Halpha`` through the Lupton R transform;
    ``CATALOG_OPTIONS['APASS']`` maps it to plain r'. Merging the registries
    would pick one and change the other's frames by ~0.15 mag.
    """
    assert CATALOGS["APASS"].filter_lookup["Halpha"].startswith("rprime - 0.2936")
    assert CATALOG_OPTIONS["APASS"].filter_lookup["Halpha"] == "rprime"


def test_only_catalog_options_carries_the_curriculum_filter_spellings():
    options = CATALOG_OPTIONS["APASS"].filter_lookup
    for key in ("gp", "rp", "ip", "Red", "Green", "Blue", "R+Red", "Green,V"):
        assert key in options
    # CATALOGS['APASS'] has its own curriculum block, so check one that differs:
    # CATALOG_OPTIONS has no OCL entries at all.
    for ocl in ("Open", "Clear", "Lum"):
        assert ocl in CATALOGS["APASS"].filter_lookup
        assert ocl not in options


# ---------------------------------------------------------------------------
# Filter-lookup merge semantics
# ---------------------------------------------------------------------------

def test_instance_lookup_does_not_leak_into_the_class():
    """``Catalog.__init__`` rebinds an instance copy rather than mutating.

    Both registries instantiate several of the same plugin classes with
    different overlays. Mutating the class dict would let entries leak between
    them — which is exactly what the ``algorithms.catalogs.catalog.Catalog`` base avoids.
    """
    from algorithms.catalogs.apass_catalog import APASSCatalog

    class_lookup = dict(APASSCatalog.filter_lookup)
    instance = APASSCatalog(filter_lookup={"ZZZ_probe": "V"})

    assert instance.filter_lookup["ZZZ_probe"] == "V"
    assert "ZZZ_probe" not in APASSCatalog.filter_lookup
    assert APASSCatalog.filter_lookup == class_lookup


def test_catalog_options_base_mutates_the_class_as_upstream_did():
    """PRESERVED DIFFERENCE: ``_MutatingCatalog`` merges in place.

    ``catalog_options.py`` documents this as kept-not-fixed, on the grounds that
    its two classes are private to that module and single-instantiation, so
    nothing observes the aliasing. Asserting it keeps the difference visible: if
    someone "fixes" it, this fails and they have to read the note.
    """
    from algorithms.catalogs.catalog_options import APASSCatalog as MutatingAPASS

    # The registry instantiation already merged its overlay into the class dict.
    assert MutatingAPASS.filter_lookup is CATALOG_OPTIONS["APASS"].filter_lookup
    assert "H_alpha" in MutatingAPASS.filter_lookup


def test_overlay_wins_over_the_class_declaration():
    from algorithms.catalogs.apass_catalog import APASSCatalog

    instance = APASSCatalog(filter_lookup={"R": "V"})
    assert instance.filter_lookup["R"] == "V"
    assert APASSCatalog.filter_lookup["R"].startswith("rprime - 0.2936")


def test_plugins_declaring_no_transforms_genuinely_have_no_attribute():
    """``Catalog`` annotates ``filter_lookup`` without assigning it.

    So a plugin that declares none has no such attribute at all, and every
    reader has to use ``getattr(..., {})``. ``algorithms.query.binding.bind_registry``
    depends on this; a stray ``filter_lookup = {}`` on the base would make the
    overlay computation silently wrong instead of failing loudly.
    """
    from algorithms.catalogs.stetson_globs_catalog import StetsonGlobsCatalog
    from algorithms.catalogs.usno_catalog import USNOB1Catalog

    assert "filter_lookup" not in vars(Catalog)
    for cls in (StetsonGlobsCatalog, USNOB1Catalog):
        assert getattr(cls, "filter_lookup", None) is None, cls.__name__


# ---------------------------------------------------------------------------
# Colour transforms
# ---------------------------------------------------------------------------

def test_ocl_filters_map_to_v_wherever_they_are_declared():
    """Open/Clear/Lum are unfiltered broadband passes; V is the closest band.

    Declared on four catalogs — the V-capable ones. A catalog without V must not
    claim to serve an unfiltered frame.
    """
    for name in ("APASS", "Landolt", "Stetson", "Tycho"):
        lookup = CATALOGS[name].filter_lookup
        for ocl in ("Open", "Clear", "Lum"):
            assert lookup[ocl] == "V", f"{name}.{ocl}"
        assert "V" in CATALOGS[name].mags


def test_lupton_transforms_are_verbatim():
    """The published coefficients, pinned exactly.

    Lupton (2005) for R and I. These are numeric calibration behaviour; a typo
    in the fourth decimal moves every R-band zero point.
    """
    lookup = CATALOGS["APASS"].filter_lookup
    assert lookup["R"] == "rprime - 0.2936*(rprime - iprime) - 0.1439"
    assert lookup["I"] == "iprime - 0.3136*(rprime - iprime) - 0.3539"


def test_jester_jordi_u_transform_is_verbatim():
    assert CATALOGS["APASS"].filter_lookup["U"] == "B + 0.78*(uprime - gprime) - 0.88"


def test_panstarrs_transforms_reference_only_bands_panstarrs_has():
    """Every PanSTARRS colour expression must resolve against its own columns.

    The PS1 -> SDSS -> ugriz' chain is two published transforms composed, so the
    expressions are long and easy to mistype. A reference to a band PanSTARRS
    does not carry would make the catalog silently unusable for that filter.
    """
    from algorithms.query.selection import _expression_deps

    catalog = CATALOGS["PanSTARRS"]
    bands = set(catalog.mags)
    for image_filter, expression in catalog.filter_lookup.items():
        deps = _expression_deps(expression)
        if deps <= bands:
            continue
        # Otherwise it must be a plain alias to another lookup entry.
        assert expression in catalog.filter_lookup or expression in bands, (
            f"{image_filter} -> {expression} references {deps - bands}"
        )


#: Lookup entries that deliberately do not resolve. ``{catalog: {filter: why}}``.
UNSATISFIABLE_LOOKUPS = {
    "APASS": {
        "U": "Jester/Jordi transform references uprime, which APASS does not carry",
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED_CATALOGS))
def test_every_transform_resolves_within_one_alias_hop(name):
    """No lookup entry may need more indirection than resolution provides.

    Both ``algorithms.query.selection`` and ``algorithms.fieldcal.ref_mag`` follow two levels: a band,
    an alias to another entry, or an expression over bands. An entry needing
    three hops would pass review and then fail at calibration time.

    ``UNSATISFIABLE_LOOKUPS`` records the entries that genuinely cannot resolve.
    They are preserved, not bugs to fix — APASS's Jester/Jordi U transform needs
    a ``uprime`` APASS has never carried, and reference-magnitude resolution
    handles that deliberately by returning ``(None, None)`` rather than falling
    back (see ``test_fieldcal_ref_mag.py``). Listing them here means a *new*
    unresolvable entry fails this test instead of joining them silently.
    """
    from algorithms.query.selection import _expression_deps, _lookup_resolves

    catalog = CATALOGS[name]
    lookup = dict(getattr(catalog, "filter_lookup", None) or {})
    bands = set(catalog.mags)
    known = UNSATISFIABLE_LOOKUPS.get(name, {})

    for image_filter, target in lookup.items():
        resolves = _lookup_resolves(target, bands, lookup)
        if image_filter in known:
            assert not resolves, (
                f"{name}: {image_filter!r} now resolves — remove it from "
                f"UNSATISFIABLE_LOOKUPS ({known[image_filter]})"
            )
            continue
        assert resolves, (
            f"{name}: {image_filter!r} -> {target!r} does not bottom out in "
            f"{sorted(bands)} (references {_expression_deps(target) - bands})"
        )


@pytest.mark.parametrize("name", sorted(UNSATISFIABLE_LOOKUPS))
def test_unsatisfiable_entries_are_declared_but_unusable(name):
    """The catalogs really do declare filters they cannot serve.

    Worth stating outright, because ``catalog_supports_filter`` returning False
    for a filter the catalog visibly lists looks like a selection bug until you
    know these exist.
    """
    from algorithms.query.selection import catalog_supports_filter

    lookup = CATALOGS[name].filter_lookup
    for image_filter in UNSATISFIABLE_LOOKUPS[name]:
        assert image_filter in lookup
        assert not catalog_supports_filter(name, image_filter)


# ---------------------------------------------------------------------------
# SIMBAD object types
# ---------------------------------------------------------------------------

def test_simbad_object_type_table_is_populated_and_string_keyed():
    assert len(SIMBAD_OBJECT_TYPES) > 100
    assert all(isinstance(k, str) and isinstance(v, str)
               for k, v in SIMBAD_OBJECT_TYPES.items())


def test_simbad_table_is_keyed_by_long_form_object_codes():
    """Keys are SIMBAD's long form (``Galaxy``, ``PN``), not the short ``G``/``*``.

    SIMBAD publishes both a short and a long code for every type. This table
    uses the long form, so a caller that looks up ``'G'`` for a galaxy gets a
    miss rather than a wrong answer — worth pinning, since the short codes are
    what most SIMBAD documentation leads with.
    """
    for code in ("Galaxy", "Star", "PN", "**"):
        assert code in SIMBAD_OBJECT_TYPES
    for short_form in ("G", "*"):
        assert short_form not in SIMBAD_OBJECT_TYPES
