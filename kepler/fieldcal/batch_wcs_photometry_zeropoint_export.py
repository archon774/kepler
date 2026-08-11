"""Batch driver: run WCS and/or photometric calibration over a directory of FITS.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/
observation_asset_processing/optical_data_processing/
batch_wcs_photometry_zeropoint_export.py (180 lines).

This is a harness, not an algorithm — it is kept because it is the reference
example of how ``perform_field_calibration`` is driven end to end, including the
exact settings the Skynet parity runs use (``min_snr=10``,
``source_match_tol=5``, ``variable_check_tol=5``, and the aperture geometry
``a=5, b=5, a_in_px=10, a_out_px=15, b_out_px=15, centroid_radius=5``).
Those literals are preserved verbatim.
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from astropy.io import fits

# EXTRACTED: was `from skynet_db.models import ObservationAssetProcessingRun`.
# EXTRACTED: was `from skynet_db.runners.common.schemas import (...)`.
from .schemas import (
    PhotometrySettings,
    PhotometricCalibrationSettings,
    ProcessingRunRef,
    SourceExtractionSettings,
)
from .field_cal import perform_field_calibration
# EXTRACTED: was `from ...optical_data_processing.wcs import solve_wcs`
# (astrometry.net / ATLAS plate solving; belongs in Kepler/wcs/).
from . import deps


# EXTRACTED: the original located the Skynet monorepo root by walking up until
# it found `packages/py/skynet-db`, then derived
#     _PIPELINE_DATA_DIR = _REPO_ROOT / ".." / "skynet-data" / "pipeline_data"
#     _TEST_SUBJECTS_ROOT = _PIPELINE_DATA_DIR / "test_subjects"
# and raised FileNotFoundError when no such ancestor existed.  That marker does
# not exist outside the Skynet monorepo, so the discovery walk is replaced with
# an explicit location: $KEPLER_PIPELINE_DATA_DIR, defaulting to ./pipeline_data.
# Behaviour of the batch run itself is unchanged; only where it looks for data.
_PIPELINE_DATA_DIR = Path(
    os.environ.get("KEPLER_PIPELINE_DATA_DIR", "pipeline_data")
)
_TEST_SUBJECTS_ROOT = _PIPELINE_DATA_DIR / "test_subjects"

RUN_DIR = "bvr"
DEFAULT_OUTPUT_CSV = _PIPELINE_DATA_DIR / "results" / "wcs_photometry_zero_points.csv"

MODE_WCS_ONLY = "wcs_only"
MODE_PHOTOMETRY_ONLY = "photometry_only"
MODE_WCS_PHOTOMETRY = "wcs_photometry"


def _load_fits(path: Path):
    with fits.open(path) as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                return hdu.data, hdu.header
    raise ValueError(f"No image data found in {path}")


def _write_wcs_to_fits(path: Path, wcs_obj) -> None:
    wcs_header = wcs_obj.to_header(relax=True)
    with fits.open(path, mode="update") as hdul:
        for hdu in hdul:
            if hdu.data is not None:
                for key, value in wcs_header.items():
                    hdu.header[key] = value
                hdul.flush()
                return
    raise ValueError(f"No image data found in {path}")


def _iter_fits_files(input_dir: Path) -> list[Path]:
    suffixes = (".fits", ".fit", ".fts", ".fits.gz")
    return sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.name.lower().endswith(suffixes)
    )


def run_batch(input_dir: Path, output_csv: Path, tmpdir: Path, *, mode: str) -> tuple[int, int]:
    fits_files = _iter_fits_files(input_dir)
    if not fits_files:
        raise FileNotFoundError(f"No FITS files found in: {input_dir}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    tmpdir.mkdir(parents=True, exist_ok=True)

    extraction_settings = SourceExtractionSettings()
    field_cal_settings = PhotometricCalibrationSettings(min_snr=10, source_match_tol=5, variable_check_tol=5)
    photometry_settings = PhotometrySettings(a=5, b=5, theta=0, a_in_px=10, a_out_px=15, b_out_px=15, theta_out_deg=0, centroid_radius=5)

    rows: list[dict[str, str | float]] = []
    success_count = 0

    for fits_path in fits_files:
        try:
            data, header = _load_fits(fits_path)
            # EXTRACTED: was `ObservationAssetProcessingRun(observation_asset_id=0)`
            processing_run = ProcessingRunRef(observation_asset_id=0)

            if mode in (MODE_WCS_ONLY, MODE_WCS_PHOTOMETRY):
                # EXTRACTED: was `solve_wcs(...)` from .wcs
                wcs, _ = deps.solve_wcs(
                    processing_run,
                    header,
                    data,
                    tmpdir,
                    extraction_settings=extraction_settings,
                )
                if wcs is None:
                    rows.append({"file": fits_path.name, "zero_point_mag": ""})
                    continue
                _write_wcs_to_fits(fits_path, wcs)

            if mode in (MODE_PHOTOMETRY_ONLY, MODE_WCS_PHOTOMETRY):
                zeropoint, _ = perform_field_calibration(
                    processing_run,
                    header,
                    data,
                    field_cal_settings=field_cal_settings,
                    photometry_settings=photometry_settings,
                    extraction_settings=extraction_settings,
                )
                rows.append({"file": fits_path.name, "zero_point_mag": float(zeropoint) if zeropoint is not None else ""})
                if zeropoint is not None:
                    success_count += 1
            else:
                rows.append({"file": fits_path.name, "zero_point_mag": ""})
        except Exception:
            rows.append({"file": fits_path.name, "zero_point_mag": ""})

    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file", "zero_point_mag"])
        writer.writeheader()
        writer.writerows(rows)

    return success_count, len(fits_files)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch run WCS and/or photometric calibration and export zero points to CSV.")
    parser.add_argument(
        "--input-dir", type=Path, default=None,
        help="Explicit FITS input directory. Defaults to "
             "<pipeline data dir>/test_subjects/<RUN_DIR>.",
    )
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--tmpdir", type=Path, default=_PIPELINE_DATA_DIR / "results" / "tmp")

    # mode_group = parser.add_mutually_exclusive_group(required=True)
    # mode_group.add_argument("--wcs-only", action="store_true", help="Run only WCS solving and write solved WCS to FITS headers.")
    # mode_group.add_argument("--photometry-only", action="store_true", help="Run only photometry using existing FITS header WCS.")
    # mode_group.add_argument("--wcs-photometry", action="store_true", help="Run WCS solving first, then photometry using solved WCS.")
    parser.set_defaults(
       wcs_only=False,
       photometry_only=True,
       wcs_photometry=False,
   )
    return parser


def _resolve_mode(args: argparse.Namespace) -> str:
    if args.wcs_only:
        return MODE_WCS_ONLY
    if args.photometry_only:
        return MODE_PHOTOMETRY_ONLY
    if args.wcs_photometry:
        return MODE_WCS_PHOTOMETRY
    raise ValueError("A processing mode must be selected.")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    mode = _resolve_mode(args)
    input_dir = (
        args.input_dir
        if args.input_dir is not None
        else _TEST_SUBJECTS_ROOT / RUN_DIR
    )

    success_count, total = run_batch(input_dir, args.output_csv, args.tmpdir, mode=mode)
    print(f"Processed {total} file(s). Zero point computed for {success_count} file(s).")
    print(f"CSV written to: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
