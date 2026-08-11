"""Kepler: astronomy database tools for scripts, notebooks, and agents.

See ``docs/tool-architecture.md`` for the shape this package follows: ordinary
Python functions under ``kepler.tools``, small shared models in
``kepler.models``, environment-backed settings in ``kepler.config``, and local
output handling in ``kepler.artifacts``.

This package does not (yet) hold the extracted algorithm folders
(``wcs``/``photometry``/``fieldcal``/``catalogs``/``query``) described in that
document's larger migration -- those stay at the repository root. Only the
database-tools slice has moved here so far.
"""

__all__: list[str] = []
