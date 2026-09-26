"""``search_vizier`` passes the requested cone to astroquery on both paths.

Offline: ``tools.vizier.Vizier`` is replaced with a recorder, so nothing here
opens a socket. The target path used to drop ``radius_arcmin`` -- astroquery's
``query_object`` was never given it, so every name search was VizieR's own 2'
cone whatever the caller asked for.
"""

from __future__ import annotations

import astropy.units as u
import pytest

from tools import vizier as vizier_tool


class _RecordingVizier:
    calls: list[tuple[str, tuple, dict]] = []

    def __init__(self, **kwargs):
        pass

    def query_object(self, *args, **kwargs):
        self.calls.append(("query_object", args, kwargs))
        return {}

    def query_region(self, *args, **kwargs):
        self.calls.append(("query_region", args, kwargs))
        return {}


@pytest.fixture
def recorded(monkeypatch):
    _RecordingVizier.calls = []
    monkeypatch.setattr(vizier_tool, "Vizier", _RecordingVizier)
    return _RecordingVizier.calls


@pytest.mark.parametrize("radius", [0.5, 1.0, 10.0])
def test_a_target_search_uses_the_requested_radius(recorded, radius):
    result = vizier_tool.search_vizier("M31", catalog="I/355/gaiadr3", radius_arcmin=radius)

    assert result.status == "not_found"
    ((method, args, kwargs),) = recorded
    assert (method, args) == ("query_object", ("M31",))
    assert kwargs["radius"] == radius * u.arcmin
    assert kwargs["catalog"] == "I/355/gaiadr3"


def test_a_target_search_defaults_to_two_arcminutes(recorded):
    vizier_tool.search_vizier("M31")

    ((_, _, kwargs),) = recorded
    assert kwargs["radius"] == 2.0 * u.arcmin


def test_a_position_search_still_uses_the_requested_radius(recorded):
    vizier_tool.search_vizier(ra_hours=0.7123, dec_degs=41.27, radius_arcmin=1.5)

    ((method, _, kwargs),) = recorded
    assert method == "query_region"
    assert kwargs["radius"] == 1.5 * u.arcmin
