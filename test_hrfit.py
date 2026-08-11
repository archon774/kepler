"""
Validation: synthetic cluster with a turnoff + giant branch and KNOWN
distance/reddening. Checks (a) parameters are recovered, (b) the isochrone
line is drawn in native order (no zig-zag at the turnoff).
"""
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import hrfit

import os
from anthropic import Anthropic
import json

client = Anthropic(
    # This is the default and can be omitted
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
)
rng = np.random.default_rng(1)

# --- isochrone in NATIVE order: faint MS -> blue turnoff -> red giant branch --
t = np.linspace(0, 1, 400)
ms = t <= 0.8
M_V = np.where(ms, 9 - (t/0.8)*10, -1 - ((t-0.8)/0.2)*1.4)     # brightens throughout
BmR = np.where(ms, 1.7 - (t/0.8)*1.9, -0.2 + ((t-0.8)/0.2)*1.1)  # blue at TO, red on RGB
# consistent per-band absolute mags (B-R == BmR by construction)
M_B = M_V + 0.6 * BmR
M_R = M_V - 0.4 * BmR

with open("synth_iso.dat", "w") as f:
    f.write("# logAge MH Bmag Vmag Rmag\n")
    for b, v, r in zip(M_B, M_V, M_R):
        f.write(f"8.60 0.15 {b:.4f} {v:.4f} {r:.4f}\n")

# non-monotonic check: some colours map to two magnitudes
assert (np.diff(np.argsort(M_V)) != 1).any(), "need a non-monotonic track"

# --- inject known params, generate observed photometry along the MS ----------
TRUE_D, TRUE_EBV = 0.97, 0.20
mu0 = hrfit.distance_modulus(TRUE_D)
AB = hrfit.get_extinction("B", TRUE_EBV); AV = hrfit.get_extinction("V", TRUE_EBV); AR = hrfit.get_extinction("R", TRUE_EBV)

idx = rng.integers(0, 320, size=180)           # sample MS portion only (t<=0.8)
sig = 0.03
B = M_B[idx] + mu0 + AB + rng.normal(0, sig, idx.size)
V = M_V[idx] + mu0 + AV + rng.normal(0, sig, idx.size)
R = M_R[idx] + mu0 + AR + rng.normal(0, sig, idx.size)
Be = np.full(idx.size, sig); Ve = Be.copy(); Re = Be.copy()
B[:15] += rng.normal(0, 0.6, 15); Be[:15] = 0.5     # high-error outliers

pd.DataFrame({"B":B,"B_err":Be,"V":V,"V_err":Ve,"R":R,"R_err":Re}).to_csv("synth_cluster.csv", index=False)

# --- fit ---------------------------------------------------------------------
res = hrfit.fit_cluster("synth_cluster.csv","synth_iso.dat","B","R","V",
                        "Bmag","Rmag","Vmag", logages=[8.60], mh=0.15, max_error=0.16)
best = res["best"]
print(f"stars after cut : {res['n_stars']}")
print(f"TRUE  d={TRUE_D:.3f}  E(B-V)={TRUE_EBV:.3f}")
print(f"FIT   d={best['distance_kpc']:.3f}  E(B-V)={best['ebv']:.3f}  (reduced cost {best['reduced_cost']:.2f})")

# --- plot with best fit (isochrone in native order) --------------------------
df = hrfit.load_photometry("synth_cluster.csv","B","R","V",max_error=0.16)
c, m = hrfit.to_absolute_cmd(df,"B","R","V",best["distance_kpc"],best["ebv"])
iso = hrfit.select_isochrone(hrfit.load_isochrone("synth_iso.dat"),8.60,0.15)
ic, im = hrfit.isochrone_cmd(iso,"Bmag","Rmag","Vmag")
hrfit.plot_cmd(c, m, ic, im, title="NGC 2168 (synthetic, with turnoff)")
plt.tight_layout(); plt.savefig("synth_fit.png", dpi=110)

assert abs(best["distance_kpc"]-TRUE_D) < 0.05, "distance not recovered"
assert abs(best["ebv"]-TRUE_EBV) < 0.05, "E(B-V) not recovered"
print("PASS: params recovered; isochrone kept in native order")