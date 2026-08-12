"""Python HR-diagram fitting: ``algorithms/hrdiagram_py/hrfit.py``.

Synthetic cluster with a turnoff + giant branch and KNOWN distance/reddening.
Checks (a) the fit recovers the injected parameters, (b) the isochrone line is
drawn in native order (no zig-zag at the turnoff). No network access -- the
isochrone here is hand-built, not fetched from PARSEC.
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from algorithms.hrdiagram_py import hrfit

TRUE_DISTANCE_KPC = 0.97
TRUE_EBV = 0.20


def test_fit_cluster_recovers_known_distance_and_reddening(tmp_path):
    rng = np.random.default_rng(1)

    # --- isochrone in NATIVE order: faint MS -> blue turnoff -> red giant branch --
    t = np.linspace(0, 1, 400)
    ms = t <= 0.8
    m_v = np.where(ms, 9 - (t / 0.8) * 10, -1 - ((t - 0.8) / 0.2) * 1.4)  # brightens throughout
    b_minus_r = np.where(ms, 1.7 - (t / 0.8) * 1.9, -0.2 + ((t - 0.8) / 0.2) * 1.1)  # blue at TO, red on RGB
    # consistent per-band absolute mags (B-R == b_minus_r by construction)
    m_b = m_v + 0.6 * b_minus_r
    m_r = m_v - 0.4 * b_minus_r

    iso_path = tmp_path / "synth_iso.dat"
    with open(iso_path, "w") as f:
        f.write("# logAge MH Bmag Vmag Rmag\n")
        for b, v, r in zip(m_b, m_v, m_r):
            f.write(f"8.60 0.15 {b:.4f} {v:.4f} {r:.4f}\n")

    # non-monotonic check: some colours map to two magnitudes
    assert (np.diff(np.argsort(m_v)) != 1).any(), "need a non-monotonic track"

    # --- inject known params, generate observed photometry along the MS ----------
    mu0 = hrfit.distance_modulus(TRUE_DISTANCE_KPC)
    a_b = hrfit.get_extinction("B", TRUE_EBV)
    a_v = hrfit.get_extinction("V", TRUE_EBV)
    a_r = hrfit.get_extinction("R", TRUE_EBV)

    idx = rng.integers(0, 320, size=180)  # sample MS portion only (t<=0.8)
    sig = 0.03
    b = m_b[idx] + mu0 + a_b + rng.normal(0, sig, idx.size)
    v = m_v[idx] + mu0 + a_v + rng.normal(0, sig, idx.size)
    r = m_r[idx] + mu0 + a_r + rng.normal(0, sig, idx.size)
    b_err = np.full(idx.size, sig)
    v_err = b_err.copy()
    r_err = b_err.copy()
    b[:15] += rng.normal(0, 0.6, 15)
    b_err[:15] = 0.5  # high-error outliers

    cluster_csv = tmp_path / "synth_cluster.csv"
    pd.DataFrame(
        {"B": b, "B_err": b_err, "V": v, "V_err": v_err, "R": r, "R_err": r_err}
    ).to_csv(cluster_csv, index=False)

    # --- fit ---------------------------------------------------------------------
    result = hrfit.fit_cluster(
        cluster_csv, iso_path, "B", "R", "V", "Bmag", "Rmag", "Vmag",
        logages=[8.60], mh=0.15, max_error=0.16,
    )
    best = result["best"]

    assert abs(best["distance_kpc"] - TRUE_DISTANCE_KPC) < 0.05, "distance not recovered"
    assert abs(best["ebv"] - TRUE_EBV) < 0.05, "E(B-V) not recovered"

    # --- plot with best fit (isochrone must stay in native order) ----------------
    df = hrfit.load_photometry(cluster_csv, "B", "R", "V", max_error=0.16)
    colour, mag = hrfit.to_absolute_cmd(df, "B", "R", "V", best["distance_kpc"], best["ebv"])
    iso = hrfit.select_isochrone(hrfit.load_isochrone(iso_path), 8.60, 0.15)
    iso_colour, iso_mag = hrfit.isochrone_cmd(iso, "Bmag", "Rmag", "Vmag")
    ax = hrfit.plot_cmd(colour, mag, iso_colour, iso_mag, title="NGC 2168 (synthetic, with turnoff)")
    ax.figure.savefig(tmp_path / "synth_fit.png", dpi=110)

    # native order means the isochrone colour trace is not sorted -- a zig-zag
    # fix would have made it monotonic in colour.
    assert (np.diff(np.argsort(iso_colour)) != 1).any()


def test_isochrone_cmd_drops_thermal_pulse_agb_rows():
    """A raw PARSEC/COLIBRI download carries a `label` evolutionary-phase
    column, and once a track enters thermally-pulsing AGB (label >= 8)
    `Mini` freezes while synthetic Gaia BP/RP swing by tens of magnitudes
    pulse to pulse -- a documented PARSEC dust/mass-loss modelling artifact,
    not real photometry (confirmed 2026-08-12 against a live NGC 6124 fetch;
    see docs/extraction.md, "HR Diagram (Python)"). Plotted or fit verbatim
    this turns a clean CMD track into a scribbled wedge and biases
    fit_distance_reddening's nearest-point cost. isochrone_cmd must drop
    those rows by default. This table is hand-built (small, exact label
    values) rather than a real PARSEC download, which needs network access."""
    iso = pd.DataFrame({
        "label": [0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 8, 9],
        "Bmag": [12.0, 10.0, 8.0, 6.0, 5.0, 4.5, 4.0, 3.8, -0.03, 42.03, -2.5, 33.8],
        "Vmag": [11.0, 9.0, 7.0, 5.0, 4.0, 3.5, 3.0, 2.8, -3.28, 26.89, -3.5, 34.0],
        "Rmag": [10.5, 8.5, 6.5, 4.5, 3.5, 3.0, 2.5, 2.3, -4.83, 23.66, -4.0, 34.3],
    })

    colour, mag = hrfit.isochrone_cmd(iso, "Bmag", "Rmag", "Vmag")
    assert len(colour) == 8, "only label <= 7 (max_label default) should survive"
    assert np.abs(colour).max() < 15 and np.abs(mag).max() < 15, \
        "the thermal-pulse rows' extreme values (mag/colour magnitudes >= 20) must not leak into the kept track"

    # max_label=None is the escape hatch back to the old unfiltered behaviour.
    colour_raw, mag_raw = hrfit.isochrone_cmd(iso, "Bmag", "Rmag", "Vmag", max_label=None)
    assert len(colour_raw) == len(iso)
    assert np.abs(colour_raw).max() > 15, "the injected thermal-pulse rows should be the extreme ones"
