"""SDSS query backend.

SDSS is the exception among Kepler's catalogs: it is not served through VizieR
but through SkyServer, which takes SQL. astroquery's ``SDSSClass`` can build
cone-search SQL but not the rectangular queries the image-footprint path needs,
and its default query does not filter on data quality. So the payload is built
here instead.

The SQL restricts to ``Star`` (not galaxies), joins ``Field`` to require
``quality = 3`` — SkyServer's "primary, good photometry" grade — and requires
``clean = 1``, SDSS's own flag for photometry with no known problems. Those two
predicates are why SDSS zero points come out usable without further filtering,
and dropping them would quietly widen the source list with unreliable rows.

EXTRACTED FROM:
``afterglow-core/afterglow_core/resources/catalog_plugins/sdss_catalog.py``
(lines 19-100 and the three query overrides) and its Skynet counterpart. Kepler
takes Skynet's ``_args_to_payload`` signature — Afterglow passed ``radius=None``
through to ``super()``, which newer astroquery rejects.
"""

from __future__ import annotations

import logging
from typing import Dict as TDict, List as TList, Optional

import numpy as np
from astropy.coordinates import Angle, SkyCoord
from astropy.units import arcmin, arcsec, deg, hour
from astroquery.sdss import SDSSClass

from kepler.catalogs.schemas import CatalogSource

from .vizier import VizierCatalog, _round_for_cache

__all__ = ["KeplerSDSS", "SDSSQueryBackend"]

logger = logging.getLogger(__name__)


class KeplerSDSS(SDSSClass):
    """``SDSSClass`` that builds Kepler's SkyServer SQL.

    EXTRACTED: was ``AfterglowSDSS``. Renamed — Kepler is not Afterglow — but
    the generated SQL is unchanged, because the quality predicates in it are
    what make SDSS photometry usable for zero-point solves.
    """

    def _args_to_payload(
        self,
        coordinates=None,
        radius=2 * arcsec,
        photoobj_fields=None,
        data_release=17,
        **kwargs,
    ):
        """Return the SkyServer request payload.

        A two-element ``radius`` tuple means a rectangular region — that is
        Kepler's extension to the astroquery signature, and it is how the
        image-footprint path asks for a box. Anything else is a cone search and
        goes through SkyServer's ``fGetNearbyObjEq``.

        The rectangular branch mirrors ``geometry.clip_sources_to_box``: the RA
        half-width is ``arcsin(sin(w/2)/cos(dec))``, not ``w/2/cos(dec)``, and a
        pole inside the region or a region straddling RA=0/360 splits into the
        same four cases. Here they become SQL predicates instead of a filter.

        Falls back to astroquery's own payload builder when the caller gave no
        coordinates, radius or field list.
        """
        if None in (coordinates, radius, photoobj_fields):
            return super()._args_to_payload(
                coordinates=None,
                photoobj_fields=photoobj_fields,
                data_release=data_release,
                **kwargs,
            )

        if isinstance(radius, tuple) and len(radius) == 2:
            # Rectangular region
            region = ''
            ra, dec = coordinates.ra.degree, coordinates.dec.degree
            h = Angle(radius[1]).to('degree').value/2
            dec_min, dec_max = dec - h, dec + h
            if dec_min < -90:
                # South Pole in FOV, use the whole RA range
                where = f's.dec <= {dec_max}'
            elif dec_max > 90:
                # North Pole in FOV, use the whole RA range
                where = f's.dec >= {dec_min}'
            else:
                w = np.rad2deg(np.arcsin(
                    np.sin(np.deg2rad(Angle(radius[0]).to('degree').value/2)) /
                    np.cos(np.deg2rad(dec))))
                ra_min, ra_max = ra - w, ra + w
                if ra_max >= ra_min + 360:
                    # RA spans the whole 360deg range
                    where = f's.dec BETWEEN {dec_min} AND {dec_max}'
                elif ra_min < 0:
                    # RA range encloses RA=0 => two separate RA ranges:
                    # ra_min + 360 <= ra <= 360 and 0 <= ra <= ra_max
                    where = f'(s.ra >= {ra_min + 360} OR s.ra <= {ra_max}) ' \
                        f'AND s.dec BETWEEN {dec_min} AND {dec_max}'
                elif ra_max > 360:
                    # RA range encloses RA=360 => two separate RA ranges:
                    # ra_min <= ra <= 360 and 0 <= ra <= ra_max - 360
                    where = f'(s.ra >= {ra_min} OR s.ra <= {ra_max - 360}) ' \
                        f'AND s.dec BETWEEN {dec_min} AND {dec_max}'
                else:
                    # RA range fully within [0, 24)
                    where = f's.ra BETWEEN {ra_min} AND {ra_max} ' \
                        f'AND s.dec BETWEEN {dec_min} AND {dec_max}'
        else:
            # Circular region
            region = 'fGetNearbyObjEq({},{},{}) AS n, '.format(
                coordinates.ra.degree, coordinates.dec.degree,
                Angle(radius).to('arcmin').value)
            where = 'n.objID = s.objID'

        # Construct SQL query
        # noinspection SqlResolve
        q = 'SELECT DISTINCT {} ' \
            'FROM {}Star AS s ' \
            'JOIN Field f ON s.fieldID = f.fieldID ' \
            'WHERE {} AND f.quality = 3 AND s.clean = 1' \
            .format(
                ', '.join(['s.{0}'.format(sql_field)
                           for sql_field in photoobj_fields]),
                region, where,
            )

        request_payload = dict(cmd=q, format='csv')

        if data_release > 11:
            request_payload['searchtool'] = 'SQL'

        return request_payload


#: Module-level template instance. ``SDSSClass`` is stateless for our purposes;
#: the query methods below call it to get a fresh instance per query, matching
#: upstream.
SDSS = KeplerSDSS()


class SDSSQueryBackend(VizierCatalog):
    """SkyServer backend for the SDSS plugin.

    Inherits ``VizierCatalog`` for ``_derive_columns`` and ``table_to_sources``
    — the column-expression machinery is provider-agnostic — but overrides all
    three query methods, so no VizieR request is ever made. The inheritance is
    upstream's arrangement and is kept; ``vizier_catalog`` stays ``None``.

    Region rounding matches ``VizierCatalog``: with the cache on, centres snap
    to 10 arcsec and sizes round up to 0.2 arcmin.

    ``constraints`` is accepted and ignored on every method — the SQL applies
    its own quality predicates and upstream never wired column filters through.
    A caller passing constraints to SDSS gets unfiltered results, silently.

    ``data_release`` comes from the plugin declaration in
    ``catalogs/sdss_catalog.py``, which also builds ``display_name`` from it —
    the two must move together, so the release is not configurable separately.
    """

    def query_objects(self, names: TList[str]) -> TList[CatalogSource]:
        """Return SDSS objects with the given names, one request each."""
        sdss = SDSS()
        rows = []
        for name in names:
            rows.append(
                sdss.query_object(
                    name,
                    data_release=self.data_release,
                    photoobj_fields=self._columns,
                    cache=self.cache,
                )[0]
            )
        return self.table_to_sources(rows)

    def query_box(
        self,
        ra_hours: float,
        dec_degs: float,
        width_arcmins: float,
        height_arcmins: Optional[float] = None,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> TList[CatalogSource]:
        """Return SDSS objects in a rectangular region."""
        if height_arcmins is None:
            height_arcmins = width_arcmins

        if self.cache:
            ra_hours, dec_degs, (width_arcmins, height_arcmins) = _round_for_cache(
                ra_hours, dec_degs, width_arcmins, height_arcmins
            )

        sdss = SDSS()
        return self.table_to_sources(
            sdss.query_region(
                SkyCoord(ra=ra_hours, dec=dec_degs, unit=(hour, deg), frame="icrs"),
                radius=(width_arcmins * arcmin, height_arcmins * arcmin),
                photoobj_fields=self._columns,
                data_release=self.data_release,
                cache=self.cache,
            )
        )

    def query_circ(
        self,
        ra_hours: float,
        dec_degs: float,
        radius_arcmins: float,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> TList[CatalogSource]:
        """Return SDSS objects within a circular region."""
        if self.cache:
            ra_hours, dec_degs, (radius_arcmins,) = _round_for_cache(
                ra_hours, dec_degs, radius_arcmins
            )

        sdss = SDSS()
        return self.table_to_sources(
            sdss.query_region(
                SkyCoord(ra=ra_hours, dec=dec_degs, unit=(hour, deg), frame="icrs"),
                radius=radius_arcmins * arcmin,
                photoobj_fields=self._columns,
                data_release=self.data_release,
                cache=self.cache,
            )
        )
