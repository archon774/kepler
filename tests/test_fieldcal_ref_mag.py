"""Reference-magnitude resolution: ``algorithms.fieldcal.ref_mag.resolve_ref_mag_for_filter``.

This is the function that decides *which catalog number a frame is calibrated
against*, so every branch here is a numeric-parity contract rather than a
convenience. Its docstring spells out a four-step resolution order — direct
band, explicit ``filter_lookup`` entry, ``'*'`` wildcard, then a gated
preferred-band fallback — and states which steps are legacy-Afterglow parity and
which are Skynet extensions. Those distinctions are what the tests below pin.

Note that this reads ``algorithms.catalogs.CATALOG_OPTIONS``, the two-catalog registry, not
``CATALOGS``. That divergence is deliberate and is tested in
``test_catalogs_registries.py``; here it just means the APASS lookup in play is
the one carrying narrowband aliases.

Modelled on ``skynet .../tests/runners/test_catalog_query.py``'s
``TestResolveRefMagBandParity`` / ``TestResolveRefMagStrictParity``.
"""

from __future__ import annotations

import pytest

from algorithms.catalogs import CATALOG_OPTIONS
from algorithms.fieldcal.ref_mag import (
    _ref_mag_filter_token_candidates,
    _safe_eval_expr,
    resolve_ref_mag_for_filter,
)
from algorithms.fieldcal.schemas import Mag


def _resolve(image_filter, mags, **kw):
    return resolve_ref_mag_for_filter(
        image_filter=image_filter, catalog_name="APASS", cs_mags=mags, **kw
    )


APASS_FULL = {
    "B": Mag(value=15.20, error=0.03),
    "V": Mag(value=14.60, error=0.02),
    "gprime": Mag(value=14.90, error=0.02),
    "rprime": Mag(value=14.40, error=0.02),
    "iprime": Mag(value=14.25, error=0.03),
}


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_direct_band_wins_over_filter_lookup():
    """A ``B`` image takes APASS's B column, never a transform onto it.

    Step 1 exists precisely to stop a lookup entry hijacking a band the catalog
    already has. Losing it would silently recalibrate every B frame.
    """
    value, error = _resolve("B", APASS_FULL)
    assert value == pytest.approx(15.20)
    assert error == pytest.approx(0.03)


def test_alias_resolves_to_a_band():
    """``r'`` -> ``rprime`` is one alias hop, and carries the band's own error."""
    value, error = _resolve("r'", APASS_FULL)
    assert value == pytest.approx(14.40)
    assert error == pytest.approx(0.02)


def test_lupton_r_transform_is_applied_with_its_published_coefficients():
    """R comes from Lupton (2005): ``r' - 0.2936*(r' - i') - 0.1439``.

    The coefficients are calibration behaviour copied verbatim from upstream, so
    the expected value is recomputed here from the same formula rather than
    hard-coded — that way this test fails if the *expression* changes, not if
    the fixture magnitudes do.
    """
    r, i = 14.40, 14.25
    expected = r - 0.2936 * (r - i) - 0.1439

    value, error = _resolve("R", APASS_FULL)
    assert value == pytest.approx(expected, rel=1e-12)

    # The error is propagated by numeric differentiation with a 1e-7 step, so it
    # must match the analytic result: R = 0.7064*r' + 0.2936*i', giving
    # sqrt((0.7064*sigma_r)^2 + (0.2936*sigma_i)^2). Note this comes out *below*
    # either input error because both partials are < 1 — a colour transform onto
    # a nearby band shrinks the uncertainty rather than inflating it.
    analytic = ((0.7064 * 0.02) ** 2 + (0.2936 * 0.03) ** 2) ** 0.5
    assert error == pytest.approx(analytic, rel=1e-5)
    assert error < min(APASS_FULL["rprime"].error, APASS_FULL["iprime"].error)


def test_lupton_i_transform_matches_the_declared_expression():
    r, i = 14.40, 14.25
    expected = i - 0.3136 * (r - i) - 0.3539
    value, _ = _resolve("I", APASS_FULL)
    assert value == pytest.approx(expected, rel=1e-12)


def test_narrowband_aliases_come_from_catalog_options_only():
    """``Halpha`` -> ``rprime`` and ``OIII`` -> ``gprime`` via NARROWBAND_FILTER_LOOKUP.

    These aliases live in ``CATALOG_OPTIONS['APASS']`` and *not* in
    ``CATALOGS['APASS']`` — the documented reason the two registries are kept
    apart. If reference-magnitude resolution were ever repointed at ``CATALOGS``,
    a narrowband frame would fall through to the preferred-band fallback and
    calibrate against V instead.
    """
    assert _resolve("Halpha", APASS_FULL)[0] == pytest.approx(14.40)
    assert _resolve("H_alpha", APASS_FULL)[0] == pytest.approx(14.40)
    assert _resolve("OIII", APASS_FULL)[0] == pytest.approx(14.90)
    assert _resolve("Hbeta", APASS_FULL)[0] == pytest.approx(14.90)


@pytest.mark.parametrize(
    "image_filter,expected_band",
    [
        ("Green", "V"),
        ("Blue", "B"),
        ("Green+V", "V"),
        ("V,Green", "V"),
        ("Blue+B", "B"),
        ("B,Blue", "B"),
    ],
)
def test_astrophotography_and_curriculum_filter_names(image_filter, expected_band):
    """The Red/Green/Blue and ``X+Y``/``X,Y`` curriculum spellings all map.

    These entries exist because student-submitted frames spell their filters
    that way; they are the reason ``CATALOG_OPTIONS['APASS']`` has 20-odd more
    lookup keys than the catalog declaration does.
    """
    assert _resolve(image_filter, APASS_FULL)[0] == pytest.approx(
        APASS_FULL[expected_band].value
    )


# ---------------------------------------------------------------------------
# The gated non-legacy fallback
# ---------------------------------------------------------------------------

def test_preferred_band_fallback_substitutes_v_by_default():
    """An unknown filter falls back to V — Skynet behaviour, not Afterglow's."""
    value, _ = _resolve("Zeta", APASS_FULL)
    assert value == pytest.approx(APASS_FULL["V"].value)


def test_preferred_band_fallback_order_is_v_rprime_gprime_b_iprime():
    """Each preferred band is used only when the ones before it are absent."""
    order = ["V", "rprime", "gprime", "B", "iprime"]
    available = dict(APASS_FULL)
    for band in order:
        value, _ = _resolve("Zeta", available)
        assert value == pytest.approx(available[band].value), f"expected {band}"
        del available[band]


def test_preferred_band_fallback_falls_through_to_any_band_last():
    """With none of the preferred bands present, any remaining band is taken."""
    value, _ = _resolve("Zeta", {"zprime": Mag(value=13.75, error=0.04)})
    assert value == pytest.approx(13.75)


def test_strict_parity_mode_refuses_to_substitute():
    """``allow_preferred_band_fallback=False`` returns ``(None, None)``.

    This is the flag the Afterglow parity diagnostic and strict field
    calibration pass. Legacy Afterglow skips a source it cannot resolve; the
    fallback would quietly calibrate it against the wrong band instead, which is
    exactly the failure this gate exists to prevent.
    """
    assert _resolve("Zeta", APASS_FULL, allow_preferred_band_fallback=False) == (None, None)


def test_explicit_lookup_that_cannot_resolve_blocks_the_fallback():
    """A matched-but-unsatisfiable lookup entry short-circuits to ``(None, None)``.

    ``U`` maps to ``B + 0.78*(uprime - gprime) - 0.88`` and APASS carries no
    ``uprime``. Because an explicit entry *was* found, ``explicit_lookup_seen``
    is set and resolution returns empty rather than continuing to the wildcard
    or the preferred-band fallback — even with the fallback enabled. Silently
    substituting V for a U-band frame is a ~1.5 mag error.
    """
    assert _resolve("U", APASS_FULL) == (None, None)
    assert _resolve("U", APASS_FULL, allow_preferred_band_fallback=False) == (None, None)


# ---------------------------------------------------------------------------
# Inputs and overrides
# ---------------------------------------------------------------------------

def test_custom_filter_lookup_overlays_the_catalog_lookup():
    """A deployment can teach a catalog a filter Kepler ships no transform for."""
    value, _ = _resolve(
        "Sloan_r",
        APASS_FULL,
        custom_filter_lookup={"APASS": {"Sloan_r": "rprime"}},
    )
    assert value == pytest.approx(14.40)


def test_custom_filter_lookup_can_override_a_shipped_transform():
    value, _ = _resolve(
        "R", APASS_FULL, custom_filter_lookup={"APASS": {"R": "V"}}
    )
    assert value == pytest.approx(APASS_FULL["V"].value)


def test_mags_accept_dicts_and_bare_floats_as_well_as_mag_objects():
    """Callers hand this three shapes; all three must flatten identically.

    ``CatalogSource.mags`` holds ``Mag`` objects, JSON payloads arrive as dicts,
    and some upstream call sites pass bare floats.
    """
    as_mag = _resolve("V", {"V": Mag(value=14.6, error=0.02)})
    as_dict = _resolve("V", {"V": {"value": 14.6, "error": 0.02}})
    as_float = _resolve("V", {"V": 14.6})

    assert as_mag == as_dict
    assert as_float == (14.6, None)


def test_unparseable_magnitude_is_treated_as_missing_not_raised():
    assert _resolve("V", {"V": object()}) == (None, None)


def test_empty_mags_returns_none_without_consulting_the_catalog():
    assert _resolve("V", {}) == (None, None)


def test_unknown_catalog_name_still_resolves_a_direct_band():
    """Step 1 does not need a catalog: it reads the image filter against mags.

    Only the lookup-driven steps consult ``CATALOG_OPTIONS``, so an unknown name
    degrades to "no transforms available" rather than failing.
    """
    value, _ = resolve_ref_mag_for_filter(
        image_filter="V", catalog_name="NoSuchCatalog", cs_mags=APASS_FULL
    )
    assert value == pytest.approx(14.60)


def test_none_filter_falls_through_to_the_preferred_band():
    value, _ = _resolve(None, APASS_FULL)
    assert value == pytest.approx(APASS_FULL["V"].value)


# ---------------------------------------------------------------------------
# Expression evaluation guardrails
# ---------------------------------------------------------------------------

def test_error_propagation_can_be_disabled():
    """``propagate_error=False`` skips the numeric-derivative pass entirely."""
    _, with_error = _resolve("R", APASS_FULL, propagate_error=True)
    _, without_error = _resolve("R", APASS_FULL, propagate_error=False)
    assert with_error is not None
    assert without_error is None


def test_expression_evaluator_rejects_anything_outside_the_token_allowlist():
    """``_ALLOWED_TOKENS`` is a security boundary, not a formatting rule.

    ``_safe_eval_expr`` ends in ``eval``. Its guard is a regex fullmatch over
    ``[A-Za-z0-9_+\\-*/().\\s]``, which is what keeps subscripts, attribute
    access, quotes and comparisons out. Everything rejected here would otherwise
    reach the interpreter.
    """
    bands = {"r": 14.4, "i": 14.25}
    assert _safe_eval_expr("r - 0.5*(r - i)", bands) == pytest.approx(14.325)
    for hostile in (
        "__import__('os').system('true')",
        "r.__class__",
        "[r][0]",
        "r if r > i else i",
        "r == i",
    ):
        assert _safe_eval_expr(hostile, bands) is None


def test_expression_evaluator_returns_none_for_non_finite_results():
    """Division by zero yields ``None``, not ``inf`` propagated into a magnitude."""
    assert _safe_eval_expr("r/(i - i)", {"r": 14.4, "i": 14.25}) is None


def test_expression_evaluator_only_exposes_sqrt_and_log10():
    bands = {"r": 100.0}
    assert _safe_eval_expr("log10(r)", bands) == pytest.approx(2.0)
    assert _safe_eval_expr("sqrt(r)", bands) == pytest.approx(10.0)
    assert _safe_eval_expr("sin(r)", bands) is None
    assert _safe_eval_expr("abs(r)", bands) is None


def test_apostrophe_band_names_cannot_appear_inside_an_expression():
    """A quirk worth pinning: the allowlist runs *before* name sanitisation.

    ``_safe_eval_expr`` does rewrite ``g'`` to ``g_`` in both the namespace and
    the expression — but only after ``_ALLOWED_TOKENS.fullmatch(expr)`` has
    already rejected the raw string, because ``'`` is not in the allowed
    character class. So the sanitiser is unreachable for exactly the names it
    looks like it was written for.

    This is why every shipped colour transform is written over ``gprime`` /
    ``rprime`` / ``iprime`` and never over ``g'`` / ``r'`` / ``i'``, with the
    apostrophe spellings handled one level up as plain aliases. Anyone adding a
    transform has to follow that convention; a ``g'``-spelled expression would
    fail silently, resolving to ``None`` rather than raising.
    """
    assert _safe_eval_expr("g' + 1", {"g'": 14.9}) is None
    assert _safe_eval_expr("gprime + 1", {"gprime": 14.9}) == pytest.approx(15.9)

    # And the aliases really are plain aliases, not expressions.
    for alias, band in (("g'", "gprime"), ("r'", "rprime"), ("i'", "iprime")):
        assert CATALOG_OPTIONS["APASS"].filter_lookup[alias] == band


# ---------------------------------------------------------------------------
# Token candidates — must agree with query.selection
# ---------------------------------------------------------------------------

def test_original_casing_is_tried_before_case_variants():
    """``Halpha`` must not be lower-cased into a miss before it is tried as-is.

    SkyMapper distinguishes ``v`` from Johnson ``V``, so the order here is
    load-bearing, not cosmetic.
    """
    assert _ref_mag_filter_token_candidates("Halpha")[0] == "Halpha"
    assert _ref_mag_filter_token_candidates(" v ")[:2] == [" v ", "v"]


def test_typographic_apostrophes_are_normalised_to_ascii():
    for variant in ("g′", "g’"):
        assert "g'" in _ref_mag_filter_token_candidates(variant)


def test_candidate_list_has_no_duplicates_and_no_empty_tokens():
    for image_filter in ("V", " V ", "g'", "Halpha", "  "):
        candidates = _ref_mag_filter_token_candidates(image_filter)
        assert len(candidates) == len(set(candidates))
        assert all(candidates)


def test_ref_mag_and_selection_token_candidates_agree():
    """The two token generators must not drift apart.

    ``algorithms.query.selection`` uses its own copy to preselect catalogs. If it accepted
    a spelling this module rejects, selection would keep a catalog that
    reference-magnitude resolution then refuses to use, and the frame would fail
    calibration with no diagnostic.
    """
    from algorithms.query.selection import _filter_token_candidates

    for image_filter in ("V", " v ", "g'", "Halpha", "g’", "OIII"):
        mine = _ref_mag_filter_token_candidates(image_filter)
        theirs = [t for t in _filter_token_candidates(image_filter) if t]
        assert mine == theirs, image_filter


# ---------------------------------------------------------------------------
# The registry this module actually reads
# ---------------------------------------------------------------------------

def test_resolution_reads_catalog_options_not_catalogs():
    """Proven by a key that only exists in one of the two registries."""
    from algorithms.catalogs import CATALOGS

    assert "H_alpha" in CATALOG_OPTIONS["APASS"].filter_lookup
    assert "H_alpha" not in CATALOGS["APASS"].filter_lookup
    assert _resolve("H_alpha", APASS_FULL)[0] == pytest.approx(14.40)
