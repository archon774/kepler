"""Optional data bundles: build them, and fetch them onto an installed Kepler (C7).

A wheel ships the core data -- the five pulsar scans, the field-calibration
references, the Afterglow parity fixtures -- and nothing else
(``docs/working/mcp-tool-surface.md`` §3.5). Two bundles are too large for it
and are published separately, as GitHub release assets (C8):

- ``optical`` -- the bundled frame library, ``data/optical/`` (~257 MB);
- ``isochrones`` -- the Girardi grid ``run_full_hr_pipeline`` fits against
  (~364 MB), which is operator-supplied and not in the repository at all.

**The manifest pins the bytes.** ``bundles.json`` beside this module records,
for each bundle, the archive's name, size and SHA-256, and it ships inside the
wheel. An installed Kepler accepts only the archive its own manifest names, so
a wheel cannot silently fetch a bundle built for a different release -- the
silent-wrong-answer failure C8 warns about.

**Archives are deterministic.** Plain ``.tar``, members sorted, with fixed
mode, owner and timestamp, so building the same tree twice gives the same
checksum anywhere. Not gzipped: compressed output can differ between zlib
versions, which would make the checksum irreproducible, and FITS barely
compresses.

**Fetching** (``kepler-mcp fetch-data``) downloads into
``<kepler home>/bundles/.downloads/``, resuming a partial download with an HTTP
Range request; checks size and SHA-256; extracts through tarfile's ``data``
filter (no absolute paths, no ``..``, no links out of the tree) into a staging
directory; and swaps that into ``<kepler home>/bundles/<name>/``, writing the
completion marker last. ``tools.config.fetched_bundle`` reads a bundle only
once that marker exists. A second fetch of a verified bundle does nothing.
Nothing is ever written into the installed package.

Redirects are followed -- a GitHub release asset is served from a redirect --
which is safe here because the checksum, not the URL, decides what is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

import httpx

from tools import config
from tools.paths import BUNDLED_DATA_LINK

__all__ = [
    "BUNDLE_URL_ENV",
    "MANIFEST_PATH",
    "BundleError",
    "BundleSpec",
    "build_archive",
    "fetch_bundle",
    "build_main",
    "fetch_main",
    "load_manifest",
]

#: Overrides where bundles are fetched from: a URL prefix, or a local directory
#: holding the archives (for testing, and for an offline mirror).
BUNDLE_URL_ENV = "KEPLER_BUNDLE_URL"

MANIFEST_PATH = Path(__file__).parent / "bundles.json"

_CHUNK = 1 << 20
_TIMEOUT = httpx.Timeout(60.0, connect=30.0)


class BundleError(RuntimeError):
    """A bundle could not be built, fetched or verified. The message says why."""


@dataclass(frozen=True)
class BundleSpec:
    name: str
    archive: str
    size: int
    sha256: str
    files: int
    url: str
    description: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, BundleSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: BundleSpec(name=name, **entry) for name, entry in raw["bundles"].items()}


# --- building ------------------------------------------------------------------


def _members(source: Path, pattern: str = "*") -> list[Path]:
    """Every regular file under ``source`` matching ``pattern``, sorted.

    Hidden files are skipped; a symlink is refused.
    """

    files = []
    for path in sorted(source.rglob(pattern)):
        relative = path.relative_to(source)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise BundleError(f"{path} is a symlink; a bundle holds regular files only")
        if path.is_file():
            if config.is_lfs_pointer(path):
                raise BundleError(
                    f"{path} is a Git LFS pointer, not the file; run `git lfs pull` "
                    "before building a bundle"
                )
            files.append(path)
    return files


def build_archive(source: Path, archive: Path, pattern: str = "*") -> tuple[int, str, int]:
    """Write a deterministic ``.tar`` of ``source``; return (size, sha256, files).

    Refuses a symlink, and a Git LFS pointer standing in for a file that was
    never pulled -- either would be bundled, and checksummed, as the wrong bytes.

    Each member is stored under its path relative to ``source``, with mode
    0644, uid/gid 0, no owner names and mtime 0, in sorted order -- so the
    bytes depend only on the files' names and contents.
    """

    files = _members(source, pattern)
    if not files:
        raise BundleError(f"{source} holds no files to bundle")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as tar:
        for path in files:
            info = tarfile.TarInfo(path.relative_to(source).as_posix())
            info.size = path.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    return archive.stat().st_size, _sha256(archive), len(files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


# --- fetching ------------------------------------------------------------------


def _source_for(spec: BundleSpec, source: str | None) -> str:
    base = source or config.env_value(BUNDLE_URL_ENV)
    if not base:
        return spec.url
    if "://" not in base:
        return str(Path(base).expanduser() / spec.archive)
    return base.rstrip("/") + "/" + spec.archive


def _download(
    url: str,
    part: Path,
    size: int,
    *,
    client: httpx.Client,
    progress: Callable[[int, int], None],
) -> None:
    """Fetch ``url`` into ``part``, resuming from what ``part`` already holds."""

    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    if have == size:
        return
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code == 206 and have:
            mode = "ab"
        elif response.status_code == 200:
            mode, have = "wb", 0
        else:
            raise BundleError(f"GET {url} returned HTTP {response.status_code}")
        with part.open(mode) as handle:
            for block in response.iter_bytes(_CHUNK):
                handle.write(block)
                have += len(block)
                progress(have, size)


def _obtain(
    spec: BundleSpec,
    location: str,
    part: Path,
    *,
    client: httpx.Client | None,
    progress: Callable[[int, int], None],
) -> None:
    if "://" not in location:
        local = Path(location)
        if not local.is_file():
            raise BundleError(f"no archive at {local}")
        shutil.copyfile(local, part)
        return
    owned = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        _download(location, part, spec.size, client=client, progress=progress)
    except httpx.HTTPError as exc:
        raise BundleError(f"downloading {location} failed: {exc}. Run the command "
                          "again to resume.") from exc
    finally:
        if owned:
            client.close()


def _refuse_inside_package(directory: Path) -> None:
    """Never write into the ``tools`` package or the bundled data it carries."""

    for protected in (BUNDLED_DATA_LINK.parent.resolve(), config.BUNDLED_DATA_DIR):
        if config.within(directory, protected):
            raise BundleError(
                f"refusing to write a bundle into the installed package ({directory})"
            )


def fetch_bundle(
    name: str,
    *,
    source: str | None = None,
    bundles_dir: Path | None = None,
    manifest: Mapping[str, BundleSpec] | None = None,
    client: httpx.Client | None = None,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> tuple[Path, bool]:
    """Install one bundle; return (its directory, whether anything was fetched).

    Idempotent: a bundle whose marker records the manifest's checksum is left
    alone. A failed or interrupted download leaves a ``.part`` file the next
    call resumes; a checksum mismatch deletes it and raises.
    """

    manifest = load_manifest() if manifest is None else manifest
    if name not in manifest:
        raise BundleError(f"unknown bundle {name!r}; choose from {', '.join(manifest)}")
    spec = manifest[name]
    root = (config.BUNDLES_DIR if bundles_dir is None else bundles_dir).resolve()
    _refuse_inside_package(root)
    target = root / name
    marker = target / config.BUNDLE_MARKER
    if marker.is_file():
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        if recorded.get("sha256") == spec.sha256:
            return target, False

    downloads = root / ".downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    part = downloads / (spec.archive + ".part")
    _obtain(spec, _source_for(spec, source), part, client=client, progress=progress)

    size = part.stat().st_size
    digest = _sha256(part)
    if size != spec.size or digest != spec.sha256:
        part.unlink()
        raise BundleError(
            f"{spec.archive} failed verification (size {size:,}, sha256 {digest}); "
            f"this Kepler expects size {spec.size:,}, sha256 {spec.sha256}. The "
            "download was discarded."
        )

    staging = root / f".staging-{name}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(part, "r") as tar:
        members = tar.getmembers()
        if any(not member.isfile() for member in members):
            shutil.rmtree(staging)
            raise BundleError(f"{spec.archive} holds something other than regular files")
        try:
            tar.extractall(staging, filter="data")
        except (tarfile.FilterError, OSError) as exc:
            shutil.rmtree(staging)
            raise BundleError(f"{spec.archive} did not extract safely: {exc}") from exc
    if len(members) != spec.files:
        shutil.rmtree(staging)
        raise BundleError(f"{spec.archive} holds {len(members)} files, not {spec.files}")

    (staging / config.BUNDLE_MARKER).write_text(
        json.dumps(
            {
                "name": name,
                "archive": spec.archive,
                "sha256": spec.sha256,
                "files": spec.files,
                "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    part.unlink()
    return target, True


# --- the two command lines -----------------------------------------------------


def _progress_printer(label: str) -> Callable[[int, int], None]:
    last = [-1]

    def show(done: int, total: int) -> None:
        percent = int(100 * done / total) if total else 100
        if percent != last[0] and percent % 5 == 0:
            last[0] = percent
            print(f"  {label}: {percent}% of {total / 1e6:,.0f} MB", file=sys.stderr)

    return show


def fetch_main(argv: Iterable[str] | None = None) -> int:
    """``kepler-mcp fetch-data``: install optional data bundles."""

    manifest = load_manifest()
    parser = argparse.ArgumentParser(
        prog="kepler-mcp fetch-data",
        description=(
            "Fetch Kepler's optional data bundles into "
            f"{config.BUNDLES_DIR}. Checksum-verified against this install's "
            "manifest, resumable, and a no-op for a bundle already installed."
        ),
    )
    parser.add_argument(
        "bundles",
        nargs="*",
        metavar="BUNDLE",
        help=f"{', '.join(manifest)}, or 'all' (default: all).",
    )
    parser.add_argument(
        "--from",
        dest="source",
        metavar="URL_OR_DIR",
        help=f"Fetch from this URL prefix or local directory (also {BUNDLE_URL_ENV}).",
    )
    parser.add_argument(
        "--list", action="store_true", help="Show each bundle's size and status; fetch nothing."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list:
        for spec in manifest.values():
            installed = config.fetched_bundle(spec.name)
            status = f"installed at {installed}" if installed else "not installed"
            print(f"{spec.name:12s} {spec.size / 1e6:8,.0f} MB  {status}\n  {spec.description}")
        return 0

    names = list(manifest) if not args.bundles or "all" in args.bundles else args.bundles
    status = 0
    for name in names:
        try:
            target, fetched = fetch_bundle(
                name, source=args.source, progress=_progress_printer(name)
            )
        except BundleError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            status = 1
            continue
        print(f"{name}: {'installed' if fetched else 'already installed'} at {target}")
    return status


def build_main(argv: Iterable[str] | None = None) -> int:
    """``python -m tools.mcp.bundles NAME SOURCE OUT``: build one bundle archive.

    For maintainers and the release workflow. Prints the manifest entry to
    paste into ``bundles.json``; the archive is what goes on the ``data``
    release. ``--check`` fails unless the build is exactly the shipped entry --
    what the release workflow runs, so a wheel never ships a manifest its own
    source tree does not build to.
    """

    parser = argparse.ArgumentParser(prog="python -m tools.mcp.bundles")
    parser.add_argument("name")
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path, help="Directory to write the archive into.")
    parser.add_argument(
        "--include", default="*", help="Only files matching this glob (default: all)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 unless the build matches this bundle's entry in bundles.json.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    building = args.out / f"kepler-{args.name}.tar.building"
    size, digest, files = build_archive(args.source, building, args.include)
    # Content-addressed name: a release asset for one set of bytes never
    # changes, and two builds of the same tree name the same file.
    archive = building.with_name(f"kepler-{args.name}-{digest[:12]}.tar")
    building.replace(archive)
    print(json.dumps({args.name: {"archive": archive.name, "size": size, "sha256": digest,
                                  "files": files}}, indent=2))
    if args.check:
        spec = load_manifest().get(args.name)
        built = (archive.name, size, digest, files)
        if spec is None or built != (spec.archive, spec.size, spec.sha256, spec.files):
            print(
                f"{args.name}: the build does not match bundles.json -- rebuild the "
                "entry, publish the new archive, and ship them together",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(build_main())
