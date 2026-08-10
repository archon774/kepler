"""Optional astrometry.net backend driven by the system ``solve-field`` binary.

v2 note
-------
The upstream skylib bound astrometry.net **in-process** via a SWIG/C extension
(``_an_engine``), which is what forced the whole meson/C build. This rewrite
keeps the same public surface (``AstrometryNetBackend``, ``solve_field_glob``)
but drives the stock ``solve-field`` command-line tool as a subprocess, so
skylib itself stays pure-Python.

Availability is therefore a *runtime* property: ``is_available()`` returns True
only where ``solve-field`` is on PATH (Linux hosts with ``astrometry.net``
installed). On Windows it returns False and callers skip the backend — the same
contract the solver dispatch and tests already relied on.

Behaviour differences vs the SWIG engine:
- The in-process progress ``callback`` is not supported (a subprocess can't call
  back into Python); it is accepted and ignored.
- Index files come from ``config.index_path`` or the
  ``SKYLIB_ASTROMETRYNET_INDEX_PATH`` env var, written into a temporary engine
  config passed via ``--config``.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

# EXTRACTED: was `from skylib.util.angle import angdist` — shared under
# kepler.skylib_lite.util.angle.
from kepler.skylib_lite.util.angle import angdist

from ..types import SolveRequest, SolveSolution
from .config import AstrometryNetConfig
from .errors import (
    AstrometryNetError,
    IndexDirectoryError,
    SolveFieldFailed,
    SolveFieldNotFoundError,
    SolveFieldTimeout,
    format_command,
)
from .engine import (
    detect_index_conventions,
    find_solve_field,
    load_ngc_globular_clusters,
    resolve_index_dirs,
    solve_field_candidates,
    validate_index_dirs,
)

logger = logging.getLogger(__name__)

#: Wall-clock grace added on top of solve-field's own ``--cpulimit`` for the
#: subprocess timeout. ``--cpulimit`` makes the engine stop *cleanly* at the
#: budget (exit 0, no .wcs → ordinary "no solution"); this slightly-larger outer
#: wall-clock limit is a hard backstop that fires (terminating the process group)
#: only if the clean stop is missed, e.g. a genuinely hung process.
_SUBPROCESS_TIMEOUT_GRACE_SEC = 30.0


def _as_text(value) -> Optional[str]:
    """Coerce captured subprocess output (bytes or str) to text, or None."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


class AstrometryNetBackend:
    name = "an"

    def is_available(self, config: Optional[AstrometryNetConfig] = None) -> bool:
        """True iff a ``solve-field`` binary can be resolved.

        Honors an explicit ``config.solve_field_path`` (so a binary configured in
        ``dev.local.toml`` but absent from ``PATH`` still counts as available),
        falling back to the env var / ``PATH`` discovery order.
        """
        explicit = getattr(config, "solve_field_path", None) if config is not None else None
        return find_solve_field(explicit) is not None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _write_index_config(index_dirs: List[str], work: Path) -> Path:
        cfg = work / "engine.cfg"
        lines = ["inparallel", "autoindex"]
        for d in index_dirs:
            lines.append(f"add_path {d}")
        cfg.write_text("\n".join(lines) + "\n", encoding="ascii")
        return cfg

    @staticmethod
    def _write_xylist(request: SolveRequest, work: Path) -> Path:
        """Write the field sources as an xylist FITS table for solve-field."""

        xy = np.asarray(request.xy, dtype=float)
        cols = {"X": xy[:, 0], "Y": xy[:, 1]}
        if request.flux is not None:
            flux = np.asarray(request.flux, dtype=float)
            if len(flux) != len(xy):
                raise ValueError("flux must match xy length")
            # Brightest-first; honour max_sources by truncating the table.
            order = np.argsort(flux)[::-1]
            if request.max_sources:
                order = order[: request.max_sources]
            cols = {"X": xy[order, 0], "Y": xy[order, 1], "FLUX": flux[order]}
        path = work / "field.xyls"
        Table(cols).write(str(path), format="fits", overwrite=True)
        return path

    def _field_dims(self, request: SolveRequest) -> tuple[int, int]:
        if request.width and request.height:
            return int(request.width), int(request.height)
        xy = np.asarray(request.xy, dtype=float)
        return int(np.ceil(xy[:, 0].max())), int(np.ceil(xy[:, 1].max()))

    def _build_cmd(
        self,
        solve_field: str,
        source: Path,
        out_base: str,
        work: Path,
        cfg: Path,
        request: SolveRequest,
        *,
        use_hint: bool,
        cpulimit: Optional[int] = None,
    ) -> List[str]:
        cmd = [
            solve_field,
            "--config", str(cfg),
            "--dir", str(work),
            "--out", out_base,
            "--overwrite",
            "--no-plots",
            # Suppress ancillary outputs we don't consume.
            "--new-fits", "none",
            "--rdls", "none",
            "--corr", "none",
            "--match", "none",
            "--index-xyls", "none",
            "--solved", "none",
            "--scale-units", "arcsecperpix",
            "--scale-low", str(float(request.min_scale)),
            "--scale-high", str(float(request.max_scale)),
        ]

        if source.suffix == ".xyls":
            width, height = self._field_dims(request)
            cmd += [
                "--x-column", "X",
                "--y-column", "Y",
                "--width", str(width),
                "--height", str(height),
            ]
            if request.flux is not None:
                cmd += ["--sort-column", "FLUX"]

        if request.crpix_center:
            cmd.append("--crpix-center")

        sip_order = int(request.sip_order or 0)
        cmd += ["--tweak-order", str(sip_order if sip_order >= 2 else 0)]

        if request.parity is not None and request.parity != "":
            cmd += ["--parity", "pos" if int(request.parity) else "neg"]

        if request.downsample:
            cmd += ["--downsample", str(int(request.downsample))]

        if use_hint and float(request.radius) < 180.0:
            cmd += [
                "--ra", str(float(request.ra_hours) * 15.0),
                "--dec", str(float(request.dec_degs)),
                "--radius", str(float(request.radius)),
            ]

        if cpulimit:
            cmd += ["--cpulimit", str(int(cpulimit))]

        cmd.append(str(source))
        return cmd

    @staticmethod
    def _read_solution(work: Path, out_base: str) -> Optional[WCS]:
        wcs_path = work / f"{out_base}.wcs"
        if not wcs_path.exists():
            return None
        try:
            return WCS(fits.getheader(str(wcs_path)))
        except Exception:
            return None

    # -- main entry -------------------------------------------------------
    def solve(self, request: SolveRequest, config: AstrometryNetConfig) -> SolveSolution:
        if not isinstance(config, AstrometryNetConfig):
            raise ValueError("Astrometry.net config is required")

        solve_field = find_solve_field(config.solve_field_path)
        if solve_field is None:
            raise SolveFieldNotFoundError(solve_field_candidates(config.solve_field_path))

        index_dirs = resolve_index_dirs(config.index_path)
        usable_dirs, problems = validate_index_dirs(index_dirs)
        if not usable_dirs:
            raise IndexDirectoryError(configured=index_dirs, problems=problems)
        accepted = ", ".join(
            f"{d} [{'+'.join(detect_index_conventions(d)) or 'unknown'}]"
            for d in usable_dirs
        )
        logger.info("anet: %d index dir(s) accepted: %s", len(usable_dirs), accepted)
        if problems:
            logger.warning(
                "anet: rejected %d unusable index dir(s): %s",
                len(problems), "; ".join(problems),
            )

        if request.image_path is None and request.xy is None:
            raise ValueError("either image_path or xy must be provided")

        with tempfile.TemporaryDirectory(prefix="skylib_anet_") as tmp:
            work = Path(tmp)
            cfg = self._write_index_config(usable_dirs, work)
            if request.image_path is not None:
                source = Path(request.image_path)
            else:
                source = self._write_xylist(request, work)

            wcs = self._run(solve_field, source, work, cfg, request, use_hint=True, config=config)

            # retry_lost: if a hinted solve failed, fall back to a blind solve.
            if (
                wcs is None
                and request.retry_lost
                and float(request.radius) < 180.0
            ):
                wcs = self._run(
                    solve_field, source, work, cfg, request, use_hint=False, config=config
                )

        sol = SolveSolution(backend=self.name)
        sol.wcs = wcs
        return sol

    @staticmethod
    def _list_workdir(work: Path) -> List[str]:
        try:
            return sorted(p.name for p in work.iterdir())
        except OSError:
            return []

    @staticmethod
    def _kill_process_group(proc: "subprocess.Popen") -> None:
        """Terminate ``proc``'s whole process group (SIGTERM, then SIGKILL).

        ``solve-field`` spawns an ``astrometry-engine`` child; killing only the
        immediate process would orphan the engine — the 12–16 min runaways the
        timeout exists to prevent. The process is started with
        ``start_new_session=True``, so its PID is its process-group leader and we
        can signal the entire tree. Best-effort: never raises.
        """
        try:
            pgid = os.getpgid(proc.pid)
        except (OSError, ProcessLookupError):
            pgid = None

        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    proc.send_signal(sig)
            except (OSError, ProcessLookupError):
                return  # already gone
            try:
                proc.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                continue
            except (OSError, ValueError):
                return

    @staticmethod
    def _invoke_solve_field(
        cmd: List[str], work: Path, timeout: Optional[float]
    ) -> "subprocess.CompletedProcess[str]":
        """Run solve-field, raising a structured error on any hard failure.

        The child runs in its own process group (``start_new_session``) so a
        timeout terminates the whole solve-field → astrometry-engine tree instead
        of orphaning the engine. Raises :class:`SolveFieldNotFoundError` if the
        binary vanished between resolution and exec, :class:`SolveFieldTimeout` on
        timeout (after killing the group and reaping), and
        :class:`SolveFieldFailed` on a nonzero exit (carrying stdout/stderr).
        """
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(work),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise SolveFieldNotFoundError([cmd[0]]) from exc

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # Kill the entire process group, then drain pipes / reap so no
            # solve-field or astrometry-engine child is left running and no
            # zombie or open pipe leaks.
            AstrometryNetBackend._kill_process_group(proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, ValueError):
                stdout, stderr = None, None
            raise SolveFieldTimeout(
                cmd,
                timeout if timeout is not None else 0.0,
                stdout=_as_text(getattr(exc, "stdout", None)) or stdout,
                stderr=_as_text(getattr(exc, "stderr", None)) or stderr,
            ) from exc

        if proc.returncode != 0:
            raise SolveFieldFailed(
                cmd,
                proc.returncode,
                stdout=stdout,
                stderr=stderr,
                workdir_listing=AstrometryNetBackend._list_workdir(work),
            )
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

    def _run(
        self,
        solve_field: str,
        source: Path,
        work: Path,
        cfg: Path,
        request: SolveRequest,
        *,
        use_hint: bool,
        config: AstrometryNetConfig,
    ) -> Optional[WCS]:
        out_base = "solve"
        cpulimit = int(config.timeout_s) if config.timeout_s else None
        cmd = self._build_cmd(
            solve_field, source, out_base, work, cfg, request,
            use_hint=use_hint, cpulimit=cpulimit,
        )
        cmd += list(config.extra_args)
        # Clean any prior .wcs so a stale file isn't mistaken for success.
        wcs_path = work / f"{out_base}.wcs"
        try:
            wcs_path.unlink()
        except OSError:
            pass

        # solve-field's own --cpulimit bounds the engine; the subprocess timeout
        # is a hard outer backstop (terminating the process group) so a hung
        # process can't run forever.
        subprocess_timeout = None
        if config.timeout_s:
            subprocess_timeout = float(config.timeout_s) + _SUBPROCESS_TIMEOUT_GRACE_SEC

        self._invoke_solve_field(cmd, work, subprocess_timeout)

        wcs = self._read_solution(work, out_base)
        if wcs is None:
            # solve-field exits 0 even when it can't solve a field; report the
            # diagnostics (no .wcs produced) but let the caller treat it as a
            # plain "no solution" so the configured ATLAS fallback can run.
            logger.info(
                "anet: solve-field produced no %s.wcs (no solution). "
                "command=%s workdir=%s",
                out_base,
                format_command(cmd),
                ", ".join(self._list_workdir(work)) or "(empty)",
            )
        return wcs


def solve_field_glob(
    request: SolveRequest,
    config: AstrometryNetConfig,
    min_sources: int = 10,
    initial_radius: float = 1,
    radius_step: float = 0.8,
) -> SolveSolution:
    """Solve a field, refining around globular clusters by masking their cores.

    Solves once, then for each known globular cluster overlapping the field,
    re-solves with the cluster's crowded core removed (cluster stars confuse the
    quad matcher). Pure-Python; the cluster list comes from the bundled NGC
    catalog instead of the old in-process engine.
    """

    backend = AstrometryNetBackend()
    sol = backend.solve(request, config)

    if sol.wcs is not None and request.xy is not None and len(request.xy) >= min_sources:
        n = len(request.xy)
        xy = np.asarray(request.xy)
        flux = np.asarray(request.flux) if request.flux is not None else np.zeros(n)
        ra, dec = sol.wcs.all_pix2world(xy[:, 0], xy[:, 1], 1)
        ra %= 360
        ra /= 15
        radius = (dec.max() - dec.min()) / 2
        for ra0, dec0, r0 in load_ngc_globular_clusters():
            r = r0 * initial_radius
            found = False
            prev_num_outer = None
            while True:
                inner = angdist(ra0, dec0, ra, dec) < r
                num_inner = inner.sum()
                if not num_inner:
                    break
                found = True
                outer = ~inner
                num_outer = n - num_inner
                if num_outer >= min_sources and num_outer != prev_num_outer:
                    prev_num_outer = num_outer
                    new_request = SolveRequest(
                        xy=xy[outer],
                        flux=flux[outer],
                        width=request.width,
                        height=request.height,
                        ra_hours=sol.wcs.wcs.crval[0] / 15,
                        dec_degs=sol.wcs.wcs.crval[1],
                        radius=radius,
                        min_scale=request.min_scale,
                        max_scale=request.max_scale,
                        parity=request.parity,
                        sip_order=0,
                        crpix_center=request.crpix_center,
                        max_sources=request.max_sources,
                        retry_lost=False,
                        callback=request.callback,
                    )
                    try:
                        new_sol = backend.solve(new_request, config)
                    except AstrometryNetError as exc:
                        # A refinement re-solve failing must not discard the
                        # good primary solution; log and keep what we have.
                        logger.warning("anet: globular-cluster re-solve failed: %s", exc)
                        break
                    if new_sol.wcs is not None:
                        sol = new_sol
                        break
                r *= radius_step
            if found:
                break
    return sol


__all__ = ["AstrometryNetBackend", "solve_field_glob"]
