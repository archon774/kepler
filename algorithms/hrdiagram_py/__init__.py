"""Python star-cluster CMD/HR-diagram pipeline.

``hrfit`` is a deliberate parity *port* of Astromancer's TypeScript, plus a
distance/E(B-V)/age optimizer Astromancer never had; its own tool is manual and
by-eye only. See ``algorithms.hrdiagram_py.hrfit`` for the exact upstream
cross-references, retired intermediate extraction, and two named permanent
parity deviations. See ``docs/extraction.md``, "HR Diagram (Python)", for the
full record.

The other modules here (``observations``, ``matching``, ``literature``,
``membership``, ``isochrones`` and ``local_grid``) are original orchestration, not extracted or
ported from either upstream system. None of them perform network I/O for
catalog access -- fetching Gaia DR3 and cluster-parameter rows from VizieR is
owned by ``tools.hr_diagram``, one layer up, via the existing
``tools.vizier.search_vizier``. This package stays Astropy-native and
JSON/artifact-ignorant, per ``docs/tool-architecture.md``.
"""

__all__ = ["hrfit", "observations", "matching", "literature", "membership", "isochrones", "local_grid", "legacy"]
