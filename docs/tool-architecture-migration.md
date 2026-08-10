# Kepler Tool Architecture — Simple Migration

Date: 2026-08-10
Status: proposed, simplified

This is the direct path from the current extracted folders to a basic Python
tool package. The goal is not to build infrastructure. The goal is to make the
existing Kepler algorithms callable through small, useful Python functions.

---

## 1. Target Shape

```text
kepler/
  __init__.py
  tools/
    __init__.py
    astrometry.py
    photometry.py
    calibration.py
    catalogs.py
    query.py
    workspace.py
  models.py
  config.py
  artifacts.py

  wcs/
  photometry/
  fieldcal/
  catalogs/
  query/

database_tools.py       # temporary compatibility wrapper
lightcurve/             # unchanged until a Python wrapper is needed
periodogram/            # unchanged until a Python wrapper is needed
hrdiagram/              # unchanged until a Python wrapper is needed
```

The `tools/` modules are the public API. The moved algorithm folders keep the
detailed implementation.

---

## 2. Step Order

### Step 1 — Create the package shell

- Add `kepler/__init__.py`.
- Add `kepler/tools/__init__.py`.
- Add small shared modules:
  - `kepler/models.py`
  - `kepler/config.py`
  - `kepler/artifacts.py`

Keep these files small. They should support the first tools, not anticipate every
future tool.

### Step 2 — Move the Python algorithm folders

Move these folders under `kepler/`:

- `wcs/` → `kepler/wcs/`
- `photometry/` → `kepler/photometry/`
- `fieldcal/` → `kepler/fieldcal/`
- `catalogs/` → `kepler/catalogs/`
- `query/` → `kepler/query/`

Update imports and package metadata for the new `kepler.` prefix. Do not reshape
the algorithm internals while moving them.

### Step 3 — Add the first simple tools

Implement the local, low-dependency tools first:

- `tools.catalogs.list_photometric_catalogs`
- `tools.catalogs.resolve_reference_band`
- `tools.calibration.solve_zeropoint_from_measurements`
- `tools.astrometry.describe_image_wcs`
- `tools.workspace.list_artifacts`
- `tools.workspace.describe_artifact`

These prove the package shape without needing remote services, solver data, or a
TypeScript runtime.

### Step 4 — Replace global field-calibration wiring

`fieldcal.deps` is useful as an extraction seam, but tool calls should not mutate
process globals.

- Add a small `FieldCalDeps` object.
- Let field calibration accept explicit dependencies.
- Keep `fieldcal.deps` as a compatibility default.
- Have `tools.calibration` pass explicit dependencies.

This is a wiring cleanup only. Do not change calibration math in this step.

### Step 5 — Add image and catalog tools

Add the heavier Python tools once the local tools are in place:

- `tools.astrometry.solve_astrometry`
- `tools.photometry.extract_sources`
- `tools.photometry.measure_photometry`
- `tools.calibration.calibrate_zeropoint`
- `tools.query.resolve_target`
- `tools.query.search_catalog`
- `tools.query.search_catalogs_for_image`

Each tool should return a compact summary and write large results to local
artifact files.

### Step 6 — Keep `database_tools.py` as a wrapper

Move useful database-query behavior into `kepler/tools/query.py` or later
`kepler/tools/literature.py`, but keep `database_tools.py` at the repository root
as a compatibility entry point while callers are updated.

### Step 7 — Defer TypeScript tools

Leave `lightcurve/`, `periodogram/`, and `hrdiagram/` where they are until there
is a concrete Python tool to expose. When that happens, start with the simplest
wrapper that can run the existing implementation and return JSON.

---

## 3. Tool Implementation Pattern

Each tool should follow the same simple shape:

```python
def tool_name(...):
    inputs = normalize_inputs(...)
    result = call_kepler_algorithm(inputs)
    return summarize_result(result)
```

Use a helper inside the same module when that keeps the tool readable. Move code
elsewhere only after more than one tool actually needs it.

---

## 4. What Changes For Users

Python imports move from top-level folders to the `kepler` package:

```python
from kepler.tools.astrometry import describe_image_wcs
from kepler.tools.photometry import extract_sources
from kepler.tools.calibration import solve_zeropoint_from_measurements
```

Existing direct algorithm imports become:

```python
from kepler.wcs.wcs import solve_wcs
from kepler.photometry.pipeline.photometry import run_photometry
from kepler.fieldcal import perform_field_calibration
from kepler.query.runner import query_catalogs
```

The preferred public API is `kepler.tools.*`. Direct algorithm imports remain
available for development and advanced use.

---

## 5. Keep Out Of Scope

- Reorganizing extracted helper directories.
- Consolidating shared implementation internals.
- Building a serving framework.
- Adding serving-specific logic.
- Creating migration audit machinery.
- Porting TypeScript algorithms to Python.
- Fixing numerical behavior while moving files.
