import unittest
from pathlib import Path

from tools.claude_photometry_haiku_tool import resolve_fits_path, resolve_zero_point_mag, summarize_results


class DummyHeader(dict):
    pass


class PhotometryToolSmokeTests(unittest.TestCase):
    def test_resolve_zero_point_mag_from_header(self) -> None:
        header = DummyHeader({"PHOT_M0": 17.2})
        self.assertEqual(resolve_zero_point_mag(Path("dummy.fits"), header), 17.2)

    def test_resolve_zero_point_mag_returns_none_when_missing(self) -> None:
        header = DummyHeader({"FILTER": "R"})
        self.assertIsNone(resolve_zero_point_mag(Path("dummy.fits"), header))

    def test_summarize_results_uses_supplied_magnitude_label(self) -> None:
        class DummyResult:
            def __init__(self, mag: float, flux: float) -> None:
                self.mag = mag
                self.flux = flux

        summary = summarize_results([DummyResult(12.5, 100.0), DummyResult(13.0, 200.0)], "calibrated magnitude")
        self.assertIn("median calibrated magnitude", summary)

    def test_resolve_fits_path_accepts_repo_test_subject_name(self) -> None:
        resolved = resolve_fits_path("ngc1846_cluster_r_000")
        self.assertTrue(resolved.exists())
        self.assertTrue(str(resolved).endswith("ngc1846_cluster_r_000.fits"))


if __name__ == "__main__":
    unittest.main()
