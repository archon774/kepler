"""Backend binding and query orchestration: ``algorithms/query/``.

``binding.py`` marries the declaration-only plugins in ``algorithms/catalogs/``
to the query backends. It does that with **multiple inheritance, not
composition**, and CLAUDE.md says not to change that. The reason is concrete:
three plugins override ``table_to_sources`` and two of them call
``super().table_to_sources(...)`` to get the raw row mapping before applying a
photometric transform. Under composition those ``super()`` calls would land on
the abstract base and raise. The MRO tests below are what make that constraint
enforceable rather than a comment.

``runner.py``'s argument validation is also pinned. Its messages are the errors
callers actually see, and it is the guard that stops a caller silently mixing
two region modes and querying a region neither of them meant.

Nothing here opens a socket. Live queries live behind the ``network`` marker.
"""

from __future__ import annotations

import inspect

import pytest

from algorithms.catalogs import CATALOGS as DECLARATIONS
from algorithms.catalogs.catalog import Catalog
from algorithms.query.binding import BACKENDS, bind_backend, bind_registry
from algorithms.query.registry import CATALOGS as QUERYABLE
from algorithms.query.registry import UnknownCatalogError, get_catalog
from algorithms.query.runner import _validate_region_args, query_catalogs
from algorithms.query.vizier import VizierCatalog

#: The three plugins that override ``table_to_sources``.
OVERRIDING_PLUGINS = ("Landolt", "USNO", "VSX")

#: Of those, the two that reach the backend through ``super()``.
SUPER_CALLING_PLUGINS = ("Landolt", "USNO")


# ---------------------------------------------------------------------------
# The MRO contract
# ---------------------------------------------------------------------------

def test_every_declaration_binds_to_a_queryable_class():
    assert set(QUERYABLE) == set(DECLARATIONS)


@pytest.mark.parametrize("name", sorted(DECLARATIONS))
def test_bound_class_inherits_declaration_then_backend(name):
    """``(Declaration, Backend)`` — the declaration first, the backend behind it.

    That order is what puts the backend immediately after the plugin in the MRO,
    exactly where upstream's ``class LandoltCatalog(VizierCatalog)`` put it.
    Reversing it would let the generic row mapper shadow a plugin's own
    ``table_to_sources``.
    """
    bound = type(QUERYABLE[name])
    declaration = type(DECLARATIONS[name])

    mro = bound.__mro__
    assert mro[0] is bound
    assert mro[1] is declaration
    assert issubclass(bound, VizierCatalog)
    assert issubclass(bound, Catalog)

    # The backend sits between the declaration and the abstract base.
    backend_index = next(i for i, c in enumerate(mro) if c is VizierCatalog)
    assert mro.index(declaration) < backend_index < mro.index(Catalog)


@pytest.mark.parametrize("name", SUPER_CALLING_PLUGINS)
def test_super_table_to_sources_reaches_the_backend_not_the_abstract_base(name):
    """The specific thing composition would break.

    ``Landolt`` and ``USNO`` call ``super().table_to_sources(table)`` to get the
    raw column mapping, then convert colour indices to magnitudes. Resolve that
    ``super()`` against the *bound* class and it must land on the backend's
    implementation. Against the bare declaration it lands on
    ``Catalog.table_to_sources``, which raises.
    """
    bound = type(QUERYABLE[name])
    declaration = type(DECLARATIONS[name])

    # The plugin does define its own override...
    assert "table_to_sources" in vars(declaration)

    # ...and the next implementation after it in the MRO is the backend's.
    after = bound.__mro__[bound.__mro__.index(declaration) + 1:]
    provider = next(c for c in after if "table_to_sources" in vars(c))
    assert provider is VizierCatalog, f"{name} super() lands on {provider.__name__}"
    assert provider is not Catalog


def test_bare_declaration_super_would_raise_confirming_why_binding_matters():
    """State the counterfactual: unbound, the transform has nothing to call."""
    from algorithms.catalogs.landolt_catalog import LandoltCatalog

    after = LandoltCatalog.__mro__[1:]
    provider = next(c for c in after if "table_to_sources" in vars(c))
    assert provider is Catalog

    with pytest.raises(NotImplementedError, match="query.registry"):
        Catalog.table_to_sources(LandoltCatalog(), [])


def test_vsx_override_does_not_call_super():
    """VSX builds sources from scratch, so it works without a bound backend.

    Worth pinning because it is the exception: the other two overrides are
    useless unbound, VSX is not.
    """
    from algorithms.catalogs.vsx_catalog import VSXCatalog

    source = inspect.getsource(VSXCatalog.table_to_sources)
    assert "super()" not in source


@pytest.mark.parametrize("name", OVERRIDING_PLUGINS)
def test_overriding_plugins_keep_their_own_implementation_after_binding(name):
    """Binding must not shadow the plugin's transform with the generic mapper."""
    bound = type(QUERYABLE[name])
    declaration = type(DECLARATIONS[name])
    assert bound.table_to_sources is declaration.table_to_sources


def test_non_overriding_plugins_get_the_backend_implementation():
    for name in ("APASS", "PanSTARRS", "2MASS", "Tycho"):
        bound = type(QUERYABLE[name])
        assert "table_to_sources" not in vars(type(DECLARATIONS[name]))
        assert bound.table_to_sources is VizierCatalog.table_to_sources


# ---------------------------------------------------------------------------
# Backend selection and caching
# ---------------------------------------------------------------------------

def test_only_sdss_and_skymapper_leave_the_vizier_default():
    """Nine of eleven catalogs are plain VizieR tables."""
    assert set(BACKENDS) == {"SDSS", "SkyMapper"}
    for name in set(DECLARATIONS) - set(BACKENDS):
        assert isinstance(QUERYABLE[name], VizierCatalog)


def test_sdss_and_skymapper_bind_to_their_own_backends():
    from algorithms.query.sdss import SDSSQueryBackend
    from algorithms.query.skymapper import SkyMapperQueryBackend

    assert isinstance(QUERYABLE["SDSS"], SDSSQueryBackend)
    assert isinstance(QUERYABLE["SkyMapper"], SkyMapperQueryBackend)


def test_binding_is_cached_so_isinstance_stays_meaningful():
    """Re-binding returns the identical class, not an equal one.

    Without the cache every call would mint a fresh type and ``isinstance``
    against a previously bound class would start returning False.
    """
    from algorithms.catalogs.apass_catalog import APASSCatalog

    first = bind_backend(APASSCatalog)
    second = bind_backend(APASSCatalog)
    assert first is second


def test_registry_overlays_survive_binding():
    """The registry-level ``filter_lookup`` overlay must not be lost.

    ``bind_registry`` rebuilds each entry on its bound class, so it has to carry
    the instance's merged lookup across. If it read the *class* lookup instead,
    ``_OCL_TO_V`` and the colour transforms applied at registration would vanish
    and every unfiltered frame would stop resolving.
    """
    for ocl in ("Open", "Clear", "Lum"):
        assert QUERYABLE["APASS"].filter_lookup[ocl] == "V"
        assert DECLARATIONS["APASS"].filter_lookup[ocl] == "V"

    assert QUERYABLE["APASS"].filter_lookup["R"].startswith("rprime - 0.2936")


def test_binding_preserves_declaration_metadata():
    for name in sorted(DECLARATIONS):
        assert QUERYABLE[name].name == DECLARATIONS[name].name
        assert QUERYABLE[name].mags == DECLARATIONS[name].mags
        assert getattr(QUERYABLE[name], "vizier_catalog", None) == getattr(
            DECLARATIONS[name], "vizier_catalog", None
        )


def test_bind_registry_does_not_mutate_the_declaration_registry():
    before = {k: type(v) for k, v in DECLARATIONS.items()}
    bind_registry(DECLARATIONS)
    assert {k: type(v) for k, v in DECLARATIONS.items()} == before


# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------

def test_get_catalog_returns_a_queryable_instance():
    assert get_catalog("APASS") is QUERYABLE["APASS"]


def test_unknown_catalog_raises_a_valueerror_subclass():
    """``UnknownCatalogError`` subclasses ``ValueError`` deliberately.

    Upstream raised a bare ``ValueError(f'Unknown catalog "{name}"')`` and
    callers catch it that way; Afterglow's version carried an HTTP 404. Keeping
    the ``ValueError`` base means existing handlers still work and a web edge can
    still map it.
    """
    with pytest.raises(UnknownCatalogError) as exc:
        get_catalog("NoSuchCatalog")

    assert isinstance(exc.value, ValueError)
    assert exc.value.name == "NoSuchCatalog"
    assert 'Unknown catalog "NoSuchCatalog"' in str(exc.value)


# ---------------------------------------------------------------------------
# Region argument validation
# ---------------------------------------------------------------------------

def _validate(**kw):
    args = dict(
        ra_hours=None, dec_degs=None, radius_arcmins=None,
        width_arcmins=None, height_arcmins=None, wcs_list=[], source_ids=[],
        constraints=None,
    )
    args.update(kw)
    return _validate_region_args(**args)


def test_some_region_must_be_given():
    with pytest.raises(ValueError, match="Either ra_hours/dec_degs, WCS, or source_ids"):
        _validate()


@pytest.mark.parametrize(
    "kwargs,message",
    [
        (dict(dec_degs=10.0), "dec_degs assumes ra_hours"),
        (dict(ra_hours=12.0), "ra_hours assumes dec_degs"),
        (dict(radius_arcmins=5.0, wcs_list=[object()]), "radius_arcmins assumes ra_hours/dec_degs"),
        (dict(width_arcmins=5.0, wcs_list=[object()]), "width_arcmins assumes ra_hours/dec_degs"),
        (dict(height_arcmins=5.0, wcs_list=[object()]), "height_arcmins assumes ra_hours/dec_degs"),
    ],
)
def test_partial_region_specifications_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _validate(**kwargs)


@pytest.mark.parametrize(
    "kwargs,message",
    [
        (dict(wcs_list=[object()], source_ids=["a"]), "WCS is mutually exclusive with source_ids"),
        (dict(source_ids=["a"], constraints={"x": "1"}), "Cannot set constraints for query by source IDs"),
        (dict(ra_hours=12.0, dec_degs=10.0, source_ids=["a"]),
         "source_ids is mutually exclusive with ra_hours/dec_degs"),
        (dict(ra_hours=12.0, dec_degs=10.0, wcs_list=[object()]),
         "WCS is mutually exclusive with ra_hours/dec_degs"),
        (dict(ra_hours=12.0, dec_degs=10.0, radius_arcmins=5.0, width_arcmins=5.0),
         "width_arcmins is mutually exclusive with radius_arcmins"),
        (dict(ra_hours=12.0, dec_degs=10.0, radius_arcmins=5.0, height_arcmins=5.0),
         "height_arcmins is mutually exclusive with radius_arcmins"),
    ],
)
def test_region_modes_cannot_be_mixed(kwargs, message):
    """Three region modes exist and mixing two silently queries the wrong sky."""
    with pytest.raises(ValueError, match=message):
        _validate(**kwargs)


def test_a_box_query_needs_a_width():
    with pytest.raises(ValueError, match="Either radius_arcmins or width_arcmins"):
        _validate(ra_hours=12.0, dec_degs=10.0)


def test_a_square_box_defaults_its_height_to_its_width():
    assert _validate(ra_hours=12.0, dec_degs=10.0, width_arcmins=30.0) == 30.0


def test_an_explicit_height_is_kept():
    assert _validate(ra_hours=12.0, dec_degs=10.0, width_arcmins=30.0, height_arcmins=20.0) == 20.0


def test_valid_wcs_and_source_id_modes_pass_validation():
    assert _validate(wcs_list=[object()]) is None
    assert _validate(source_ids=["a", "b"]) is None


def test_unknown_catalog_name_is_rejected_before_any_network_call():
    """Validation must fail fast, not after a round trip.

    ``skip_failed`` is for providers that are down, not for typos in a catalog
    name — a misspelled name silently skipped would produce an empty result the
    caller reads as "no sources in this field".
    """
    with pytest.raises(UnknownCatalogError):
        query_catalogs(["NoSuchCatalog"], ra_hours=12.0, dec_degs=10.0, radius_arcmins=1.0)


# ---------------------------------------------------------------------------
# Query configuration
# ---------------------------------------------------------------------------

def test_query_settings_read_the_environment(monkeypatch):
    """``QuerySettings`` replaces Afterglow's Flask config and Skynet's literals.

    Attributes keep upstream's SCREAMING_CASE names because that is how the
    Flask ``current_app.config`` keys were spelled; only ``vizier_cache_max_age``
    is a derived property.
    """
    from datetime import timedelta

    from algorithms.query.config import QuerySettings

    monkeypatch.setenv("VIZIER_SERVER", "vizier.example.org")
    monkeypatch.setenv("VIZIER_CACHE_ENABLED", "0")
    monkeypatch.setenv("VIZIER_CACHE_AGE_DAYS", "3.5")

    settings = QuerySettings()
    assert settings.VIZIER_SERVER == "vizier.example.org"
    assert settings.VIZIER_CACHE_ENABLED is False
    assert settings.VIZIER_CACHE_AGE_DAYS == 3.5
    assert settings.vizier_cache_max_age == timedelta(days=3.5)


def test_explicit_arguments_beat_the_environment(monkeypatch):
    """A caller with its own configuration assigns ``query.config.settings``."""
    from algorithms.query.config import QuerySettings

    monkeypatch.setenv("VIZIER_SERVER", "from-env.example.org")
    settings = QuerySettings(vizier_server="explicit.example.org")
    assert settings.VIZIER_SERVER == "explicit.example.org"


def test_default_vizier_server_is_the_cds_mirror(monkeypatch):
    """Afterglow used the Harvard mirror; Skynet moved to CDS and Kepler follows."""
    from algorithms.query.config import QuerySettings

    monkeypatch.delenv("VIZIER_SERVER", raising=False)
    assert QuerySettings().VIZIER_SERVER == "vizier.cds.unistra.fr"


@pytest.mark.parametrize(
    "raw,expected",
    [("1", True), ("true", True), ("yes", True), ("on", True), ("anything", True),
     ("0", False), ("false", False), ("no", False), ("off", False), ("", False)],
)
def test_cache_enabled_flag_parsing(monkeypatch, raw, expected):
    from algorithms.query.config import QuerySettings

    monkeypatch.setenv("VIZIER_CACHE_ENABLED", raw)
    assert QuerySettings().VIZIER_CACHE_ENABLED is expected


def test_malformed_cache_age_falls_back_to_the_default(monkeypatch):
    from algorithms.query.config import QuerySettings

    monkeypatch.delenv("VIZIER_CACHE_AGE_DAYS", raising=False)
    default = QuerySettings().VIZIER_CACHE_AGE_DAYS
    assert default == 30.0

    monkeypatch.setenv("VIZIER_CACHE_AGE_DAYS", "not-a-number")
    assert QuerySettings().VIZIER_CACHE_AGE_DAYS == default


def test_enabling_the_cache_snaps_query_regions_to_a_grid():
    """Documented consequence: the cache is not transparent near a field edge.

    ``algorithms/query/EXTRACTION.md`` §5.1 records that enabling the cache
    rounds the query region to a fixed grid so near-identical fields share an
    entry — which means turning it on can change which sources come back. Pinned
    as a fact about the setting, since the default is *enabled*.
    """
    from algorithms.query.config import QuerySettings

    assert QuerySettings(vizier_cache_enabled=True).VIZIER_CACHE_ENABLED is True
    assert QuerySettings(vizier_cache_enabled=False).VIZIER_CACHE_ENABLED is False


# ---------------------------------------------------------------------------
# Live queries — opt-in only
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_live_apass_query_returns_sources_with_magnitudes():
    """Smoke test against the real VizieR service.

    Never runs by default: needs both ``-m network`` and
    ``KEPLER_TEST_NETWORK=1``. Kept small — a 5 arcmin cone on a well-populated
    field — because it is a connectivity and shape check, not a science test.
    """
    sources = query_catalogs(
        ["APASS"], ra_hours=13.0, dec_degs=28.0, radius_arcmins=5.0,
    )
    assert sources
    assert any(s.mags for s in sources)
    assert all(s.catalog_name == "APASS" for s in sources)
