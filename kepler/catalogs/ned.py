"""Kepler: NASA/IPAC Extragalactic Database (NED) table vocabulary.

NED serves per-object data through several distinct tables rather than one
flat row. This module is the lookup table for that vocabulary -- which
``table`` values ``Ned.get_table`` accepts, and what each one contains -- for
``kepler.tools.ned`` to read. It is declaration only: nothing here imports
astroquery or opens a socket, matching every other module in this package.

Confirmed against the installed astroquery version's
``astroquery.ipac.ned.core.NedClass.get_table`` docstring
(astroquery==0.4.11), not guessed from documentation prose.
"""

from __future__ import annotations

__all__ = ["NED_TABLES", "NED_PHOTOMETRY_FORMATS"]

#: Valid values for ``Ned.get_table(name, table=...)``. ``photometry`` is the
#: one that answers "all historical measurements of X": NED's
#: literature-compiled table of every published flux for an object, with
#: frequency/band and reference. It is also ``get_table``'s default.
NED_TABLES: dict[str, str] = {
    "photometry": "Every published flux/magnitude measurement for the "
    "object, with frequency or band, value, and reference -- NED's "
    "compiled historical photometry.",
    "positions": "Positional measurements from the literature.",
    "diameters": "Angular size measurements from the literature.",
    "redshifts": "Redshift measurements from the literature.",
    "references": "Bibliographic references for the object, with an "
    "optional year range (`from_year`/`to_year` on `get_table`).",
    "object_notes": "Free-text notes about the object from NED's editors.",
}

#: ``output_table_format`` values accepted only when ``table='photometry'``.
#: Format 3 normalizes every measurement to mJy regardless of how the source
#: publication reported it -- the right default for aggregating flux history
#: across a century of literature that used inconsistent units.
NED_PHOTOMETRY_FORMATS: dict[int, str] = {
    1: "Data as Published and Homogenized (mJy)",
    2: "Data as Published",
    3: "Homogenized Units (mJy)",
}
