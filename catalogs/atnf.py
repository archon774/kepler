"""Kepler: ATNF Pulsar Catalogue parameter vocabulary.

``psrqpy`` (the package ``kepler.tools.atnf`` queries the ATNF catalogue
through) already carries its own complete parameter list in
``psrqpy.config``. This module copies that vocabulary as static data rather
than importing ``psrqpy`` here, so that ``catalogs/`` keeps the same
zero-query-library-import contract every other module in this package has --
"nothing here imports astroquery or opens a socket" applies equally to
psrqpy, which is the same category of dependency.

Copied verbatim from ``psrqpy.config`` (psrqpy==1.3.2): ``PSR_GENERAL_PARS``,
``PSR_TIMING_PARS``, ``PSR_BINARY_PARS``, ``PSR_DERIVED_PARS``. If psrqpy adds
parameters in a future release, this list will not automatically follow --
that is the accepted cost of not importing it. ``kepler.tools.atnf`` re-checks
against ``psrqpy.config.PSR_ALL_PARS`` at query time if the two diverge
matters for a given call.
"""

from __future__ import annotations

__all__ = [
    "PSR_GENERAL_PARAMS",
    "PSR_TIMING_PARAMS",
    "PSR_BINARY_PARAMS",
    "PSR_DERIVED_PARAMS",
    "PSR_ALL_PARAMS",
]

#: Identity, astrometry, and survey/discovery metadata.
PSR_GENERAL_PARAMS: list[str] = [
    "NAME", "JNAME", "BNAME", "PSRJ", "PSRB", "RAJ", "DECJ", "PMRA", "PMDEC",
    "PX", "POSEPOCH", "ELONG", "ELAT", "PMELONG", "PMELAT", "GL", "GB",
    "RAJD", "DECJD", "TYPE", "PML", "PMB", "DIST", "DIST_DM", "DIST_DM1",
    "DIST1", "DIST_AMN", "DIST_AMX", "DIST_A", "DMSINB", "ZZ", "XX", "YY",
    "ASSOC", "SURVEY", "OSURVEY", "DATE", "NGLT", "GLEP", "GLPH", "GLF0",
    "GLF1", "GLF0D", "GLTD", "CLK", "EPHEM",
]

#: Rotation, dispersion, and flux-density measurements.
PSR_TIMING_PARAMS: list[str] = [
    "P0", "P1", "F0", "F1", "F2", "F3", "F4", "F5", "PEPOCH", "DMEPOCH",
    "DM", "DM1", "DM2", "DM3", "RM", "W50", "W10", "UNITS", "TAU_SC",
    "SI414", "S400", "S1400", "S2000", "S40", "S50", "S60", "S80", "S100",
    "S150", "S200", "S300", "S350", "S600", "S700", "S800", "S900", "S1600",
    "S3000", "S4000", "S5000", "S6000", "S8000", "S100G", "S150G", "SPINDX",
]

#: Orbital elements for binary pulsars.
PSR_BINARY_PARAMS: list[str] = [
    "BINARY", "T0", "PB", "A1", "OM", "ECC", "TASC", "EPS1", "EPS2",
    "BINCOMP", "FB0", "FB1", "FB2", "OMDOT", "OM2DOT", "A1DOT", "A12DOT",
    "ECCDOT", "PBDOT", "GAMMA", "T0_2", "PB_2", "A1_2", "OM_2", "ECC_2",
    "EPS1_2", "EPS2_2", "TASC_2", "T0_3", "PB_3", "A1_3", "OM_3", "ECC_3",
    "SINI", "SINI_2", "SINI_3", "KOM", "KIN", "M2", "M2_2", "M2_3",
    "MASS_Q", "OM_ASC", "DTHETA", "XOMDOT", "H3", "H4", "STIG", "MASSFN",
    "MINMASS", "MEDMASS", "UPRMASS", "MINOMDOT",
]

#: Quantities the catalogue derives rather than measures directly.
PSR_DERIVED_PARAMS: list[str] = [
    "R_LUM", "R_LUM14", "AGE", "BSURF", "EDOT", "EDOTD2", "PMTOT", "VTRANS",
    "P1_I", "AGE_I", "BSURF_I", "B_LC", "H0_SD",
]

PSR_ALL_PARAMS: list[str] = (
    PSR_GENERAL_PARAMS + PSR_TIMING_PARAMS + PSR_BINARY_PARAMS + PSR_DERIVED_PARAMS
)
