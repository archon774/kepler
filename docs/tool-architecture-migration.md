# Kepler Tool Architecture — Initial Migration

Date: 2026-08-10
Status: proposed, simplified

This migration is only the first architecture pass. Its job is to make the
existing Python algorithms importable as a `kepler` package and expose a first
small set of plain Python tools. It should not fix algorithm bugs, reorganize
helper trees, or build serving infrastructure.

After this lands, the next planning pass is the algorithm remediation plan: turn
the bug backlog into focused fix PRs, each with the smallest targeted test that
proves the fix.

---

## 1. Target Shape For This Pass

```text
kepler/
  __init__.py
  tools/
    __init__.py
    astrometry.py
    calibration.py
    catalogs.py
    workspace.py
  models.py
  config.py
  artifacts.py

  wcs/
  photometry/
  fieldcal/
  catalogs/
  query/

database_tools.py       # unchanged compatibility entry point
lightcurve/             # unchanged
periodogram/            # unchanged
hrdiagram/              # unchanged
```

Only the first local tools are in scope here. Heavier image/catalog tools,
database-tool absorption, and TypeScript wrappers wait until after the first
architecture slice and the remediation plan are clearer.

---

## 2. Step 1 — Create The Package Shell

Add the minimum package structure:

- `kepler/__init__.py`
- `kepler/tools/__init__.py`
- `kepler/models.py`
- `kepler/config.py`
- `kepler/artifacts.py`
- empty tool modules for the first slice:
  - `kepler/tools/astrometry.py`
  - `kepler/tools/calibration.py`
  - `kepler/tools/catalogs.py`
  - `kepler/tools/workspace.py`

Keep the shared files intentionally small:

- `models.py`: small result, warning/error, table summary, WCS summary, and file
  metadata models as needed by the first tools.
- `config.py`: simple environment-backed settings helpers only where a first
  tool needs them.
- `artifacts.py`: local output-directory and file-description helpers. An
  artifact is just a local file path plus basic metadata.

Do not add a registry, server, plugin layer, or large model tree.

---

## 3. Step 2 — Move The Python Algorithm Folders

Move the Python algorithm folders under `kepler/`:

- `wcs/` -> `kepler/wcs/`
- `photometry/` -> `kepler/photometry/`
- `fieldcal/` -> `kepler/fieldcal/`
- `catalogs/` -> `kepler/catalogs/`
- `query/` -> `kepler/query/`

Update imports for the new package paths. Keep the algorithm internals intact:

- no numerical edits;
- no helper-tree consolidation;
- no broad cleanup while files are moving;
- no changes to TypeScript folders.

Update packaging and docs for the new import paths:

- `pyproject.toml` should discover `kepler*`.
- package data currently under `wcs.*` should move to the corresponding
  `kepler.wcs.*` package path.
- README examples should prefer `kepler.tools.*` for users and document direct
  `kepler.<algorithm_package>` imports for advanced use.

`database_tools.py` stays at the repository root in this pass.

---

## 4. Step 3 — Add The First Simple Tools

Implement only local, low-dependency tools first:

- `kepler.tools.astrometry.describe_image_wcs(path)`
- `kepler.tools.catalogs.list_photometric_catalogs()`
- `kepler.tools.catalogs.resolve_reference_band(catalog, image_filter)`
- `kepler.tools.calibration.solve_zeropoint_from_measurements(measurements, catalog_sources)`
- `kepler.tools.workspace.list_artifacts(directory=None)`
- `kepler.tools.workspace.describe_artifact(path)`

These tools prove the package shape without requiring remote catalog calls,
astrometry.net index files, local UCAC catalogs, Node, or end-to-end FITS
pipeline data.

Use the same simple pattern for each tool:

```python
def tool_name(...):
    inputs = normalize_inputs(...)
    result = call_kepler_algorithm(inputs)
    return summarize_result(result)
```

Use private helpers inside the same tool module before adding another package.
If a helper starts doing astronomy math, move that logic into the relevant
algorithm package instead.

---

## 5. Checks For This Pass

Keep validation lightweight and tied to the changed surface:

- `python3 -m py_compile database_tools.py`
- `python3 -m compileall kepler`
- a smoke import of `kepler` and the first `kepler.tools.*` modules
- `git diff --check`

Do not add broad numerical regression work here. Numerical tests belong with the
algorithm remediation PRs that actually change behavior.

---

## 6. Handoff To Algorithm Remediation

Once Steps 1-3 are done, update `algorithm-remediation-plan.md` before fixing
algorithm bugs. That refactor should:

- remove references to old architecture phases and heavy verification machinery;
- keep the finding register and blocker list;
- replace broad harness language with a rule that each fix PR adds the smallest
  targeted test for the affected behavior;
- define the first few remediation PRs, starting with blocker or tool-exposure
  risks;
- note duplicated bugs explicitly: until helper trees are intentionally
  consolidated, a fix must be applied everywhere the duplicated code exists.

The practical sequencing is:

1. Finish this architecture migration.
2. Refactor the remediation plan into targeted fix work.
3. Start bug-fix PRs with tests.

---

## 7. Out Of Scope

- Fixing numerical behavior while moving files.
- Reorganizing extracted helper directories.
- Consolidating duplicated implementation internals.
- Replacing `fieldcal.deps` unless a first-slice tool requires it.
- Adding heavier image or TypeScript-backed tools.
- Building a serving framework.

**Update:** "Moving `database_tools.py` logic" was originally listed here as
out of scope for this pass, deferred until after Steps 1-3 and the
remediation plan. It was pulled forward by explicit request ahead of that
sequencing: `kepler/tools/` now holds one thin tool per database (SIMBAD,
NED, VizieR, ATNF, MAST, MPC, CASDA), and `database_tools.py` has been
deleted. This did not do Steps 1-3 as written above — `wcs/`, `photometry/`,
`fieldcal/`, `catalogs/`, and `query/` have not moved under `kepler/`, and
`catalogs/`/`query/` were not touched at all. Only the database-tools slice
landed early; the rest of this migration is still ahead. Literature search
(ADS) was not carried over and is being redesigned separately.
