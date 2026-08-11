"""Kepler: ADS field vocabulary and citation formatting.

Declaration and text-formatting only -- no astroquery import, no socket,
matching every other module in this package. This is the "extraction layer"
for literature reviews: the field list a review needs and the logic that
turns one ADS result row into a readable reference-list citation live here,
so ``kepler.tools.ads`` stays a thin caller of astroquery plus this.

EXTRACTED FROM: NASA/SAO ADS's own search-syntax guide
(https://ui.adsabs.harvard.edu/help/search/search-syntax) for the field
names, and ``astroquery.nasa_ads.conf.adsfields`` (astroquery 0.4.11) for the
default field list ``ADS.query_simple`` requests.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ADS_DEFAULT_FIELDS",
    "ADS_REVIEW_FIELDS",
    "ADS_SEARCH_FIELDS",
    "flatten_value",
    "format_citation",
]

#: astroquery.nasa_ads's own default -- what ADS.query_simple requests unless
#: ADS.ADS_FIELDS is overridden.
ADS_DEFAULT_FIELDS: list[str] = [
    "bibcode", "title", "author", "aff", "pub", "volume", "pubdate", "page",
    "citation", "citation_count", "abstract", "doi", "eid",
]

#: Fields a literature-review citation actually needs -- narrower than the
#: default (drops "aff", "citation", "eid"). Deliberately uses "pubdate", not
#: a separate "year" field: "year" is valid in ADS *search* syntax
#: (``year:2017``) but is not in astroquery.nasa_ads's own confirmed default
#: return-field list, so it isn't trusted here as a returnable field --
#: ``format_citation`` derives the year from "pubdate"'s leading 4 characters
#: instead, which is a field this module can confirm is actually populated.
ADS_REVIEW_FIELDS: list[str] = [
    "bibcode", "title", "author", "pub", "volume", "pubdate", "page",
    "citation_count", "abstract", "doi",
]

#: Fielded-search prefixes confirmed against ADS's own search-syntax guide.
#: Declaration only -- kepler.tools.ads uses these to build a query string
#: safely rather than passing a caller's free-text search straight through,
#: which ADS's own docs warn "may not produce the expected results."
ADS_SEARCH_FIELDS: dict[str, str] = {
    "author": 'author:"{value}"',
    "first_author": 'author:"^{value}"',
    "title": 'title:"{value}"',
    "abstract": 'abs:"{value}"',
    "full_text": 'full:"{value}"',
    "year": "year:{value}",
    "bibcode": "bibcode:{value}",
    "doi": "doi:{value}",
    "object": 'object:"{value}"',
    "doctype": "doctype:{value}",
    "bibstem": "bibstem:{value}",
    "property": "property:{value}",
}


def flatten_value(value: Any) -> Any:
    """Collapse an ADS multi-valued field to something readable.

    ADS's underlying Solr response stores nearly every field as a list
    (single-element for scalar-like fields such as ``title``/``bibcode``,
    genuinely multi-valued for ``author``/``aff``). A length-1 sequence
    unwraps to its one value; a longer one joins with "; " so an author list
    reads as a name string rather than a Python repr.

    Confirmed live (offline, via a synthetic table): when every row in an
    astropy Table column happens to hold the same-length list (e.g. every
    matched paper has exactly two authors), astropy stores it as a 2-D numpy
    array cell rather than a Python list -- ``hasattr(value, "tolist")``
    catches that case too, not just plain ``list``/``tuple``.
    """
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return None
        if len(value) == 1:
            return value[0]
        return "; ".join(str(v) for v in value)
    return value


def format_citation(row: dict) -> str:
    """Format one ADS result row (keyed by ``ADS_REVIEW_FIELDS``-style names)
    as a short reference-list citation.

    Not a specific citation style (APA/AAS/etc.) -- a compact, readable line
    carrying author(s), year, venue, and identifiers, since ADS's own record
    doesn't reliably distinguish first/last page or issue for every result.
    """
    authors = flatten_value(row.get("author"))
    if authors:
        author_list = authors.split("; ") if isinstance(authors, str) else [authors]
        author_str = f"{author_list[0]}, et al." if len(author_list) > 3 else "; ".join(author_list)
    else:
        author_str = "Unknown author"

    year = str(flatten_value(row.get("pubdate")) or "")[:4]
    pub = flatten_value(row.get("pub"))
    volume = flatten_value(row.get("volume"))
    page = flatten_value(row.get("page"))
    bibcode = flatten_value(row.get("bibcode"))
    doi = flatten_value(row.get("doi"))
    citation_count = flatten_value(row.get("citation_count"))

    parts = [author_str]
    if year:
        parts.append(str(year))
    venue = pub or ""
    if venue and volume:
        venue += f", {volume}"
    if venue and page:
        venue += f", {page}"
    if venue:
        parts.append(venue)

    line = ", ".join(str(p) for p in parts if p)
    tags = []
    if bibcode:
        tags.append(f"bibcode:{bibcode}")
    if doi:
        tags.append(f"doi:{doi}")
    if citation_count is not None:
        tags.append(f"cited by {citation_count}")
    if tags:
        line += " (" + "; ".join(tags) + ")"
    return line
