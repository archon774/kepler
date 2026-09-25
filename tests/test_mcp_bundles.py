"""Optional data bundles, and the guards re-anchored for an installed layout (C7).

Offline throughout: a bundle is fetched from a local directory, and the one
HTTP path under test -- resuming a partial download with a Range request --
goes through ``httpx.MockTransport``, which opens no socket.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from tools import config
from tools.mcp import bundles
from tools.mcp.bundles import BundleError, BundleSpec, build_archive, fetch_bundle

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _tree(root: Path) -> Path:
    (root / "sub").mkdir(parents=True)
    (root / "a.fits").write_bytes(b"SIMPLE  =" + b"\0" * 64)
    (root / "sub" / "b.npy").write_bytes(b"\x93NUMPY" + b"\1" * 32)
    (root / ".hidden").write_text("skipped")
    return root


def _spec(archive: Path, name: str = "optical", **changes) -> BundleSpec:
    data = archive.read_bytes()
    spec = BundleSpec(
        name=name,
        archive=archive.name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        files=2,
        url="https://example.invalid/" + archive.name,
        description="test",
    )
    return replace(spec, **changes)


# --- the manifest ----------------------------------------------------------------


def test_the_manifest_names_content_addressed_archives():
    manifest = bundles.load_manifest()
    assert set(manifest) == {"optical", "isochrones"}
    for spec in manifest.values():
        assert spec.archive == f"kepler-{spec.name}-{spec.sha256[:12]}.tar"
        assert spec.url.endswith("/" + spec.archive)
        assert spec.url.startswith("https://github.com/archon774/kepler/releases/download/")


def test_the_optical_manifest_entry_is_a_build_of_data_optical(tmp_path):
    """The shipped checksum is what this repository's frames build to, exactly."""
    spec = bundles.load_manifest()["optical"]
    source = _REPO_ROOT / "data" / "optical"
    if any(config.is_lfs_pointer(p) for p in source.glob("*.fits")):
        pytest.skip("data/optical has Git LFS pointers; run `git lfs pull`")
    size, digest, files = build_archive(source, tmp_path / "optical.tar")
    assert (size, digest, files) == (spec.size, spec.sha256, spec.files)


# --- building --------------------------------------------------------------------


def test_builds_are_deterministic_and_skip_hidden_files(tmp_path):
    source = _tree(tmp_path / "src")
    first = build_archive(source, tmp_path / "one.tar")
    (source / "a.fits").touch()  # a new mtime must not change the bytes
    second = build_archive(source, tmp_path / "two.tar")
    assert first == second and first[2] == 2
    with tarfile.open(tmp_path / "one.tar") as tar:
        assert tar.getnames() == ["a.fits", "sub/b.npy"]
        assert {(m.mtime, m.uid, m.mode) for m in tar.getmembers()} == {(0, 0, 0o644)}


def test_a_build_refuses_lfs_pointers_and_symlinks(tmp_path):
    source = _tree(tmp_path / "src")
    (source / "c.fits").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n"
    )
    with pytest.raises(BundleError, match="Git LFS pointer"):
        build_archive(source, tmp_path / "x.tar")
    (source / "c.fits").unlink()
    (source / "link.fits").symlink_to(source / "a.fits")
    with pytest.raises(BundleError, match="symlink"):
        build_archive(source, tmp_path / "x.tar")


def test_the_include_pattern_narrows_a_build(tmp_path):
    source = _tree(tmp_path / "src")
    _, _, files = build_archive(source, tmp_path / "x.tar", "*.npy")
    assert files == 1


# --- fetching --------------------------------------------------------------------


@pytest.fixture
def published(tmp_path):
    """A built archive in a 'release' directory, and its manifest entry."""
    release = tmp_path / "release"
    release.mkdir()
    archive = release / "kepler-optical-test.tar"
    build_archive(_tree(tmp_path / "src"), archive)
    return release, _spec(archive)


def test_fetch_installs_verifies_and_marks_a_bundle(tmp_path, published):
    release, spec = published
    target, fetched = fetch_bundle(
        "optical", source=str(release), bundles_dir=tmp_path / "home", manifest={"optical": spec}
    )
    assert fetched and target == (tmp_path / "home" / "optical").resolve()
    assert (target / "a.fits").is_file() and (target / "sub" / "b.npy").is_file()
    marker = json.loads((target / config.BUNDLE_MARKER).read_text())
    assert marker["sha256"] == spec.sha256 and marker["files"] == 2
    assert list((tmp_path / "home" / ".downloads").iterdir()) == []


def test_a_second_fetch_of_a_verified_bundle_does_nothing(tmp_path, published):
    release, spec = published
    kwargs = dict(source=str(release), bundles_dir=tmp_path / "home", manifest={"optical": spec})
    fetch_bundle("optical", **kwargs)
    (release / spec.archive).unlink()  # would fail if it tried again
    _, fetched = fetch_bundle("optical", **kwargs)
    assert fetched is False


def test_a_checksum_mismatch_is_rejected_and_discarded(tmp_path, published):
    release, spec = published
    wrong = replace(spec, sha256="0" * 64)
    with pytest.raises(BundleError, match="failed verification"):
        fetch_bundle("optical", source=str(release), bundles_dir=tmp_path / "home",
                     manifest={"optical": wrong})
    assert not (tmp_path / "home" / "optical").exists()
    assert list((tmp_path / "home" / ".downloads").iterdir()) == []


def test_an_archive_escaping_its_directory_is_refused(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    archive = release / "evil.tar"
    with tarfile.open(archive, "w") as tar:
        for name in ("ok.fits", "../escaped.fits"):
            info = tarfile.TarInfo(name)
            info.size = 3
            tar.addfile(info, io.BytesIO(b"abc"))
    spec = _spec(archive)
    with pytest.raises(BundleError, match="did not extract safely"):
        fetch_bundle("optical", source=str(release), bundles_dir=tmp_path / "home",
                     manifest={"optical": spec})
    assert not (tmp_path / "home" / "escaped.fits").exists()
    assert not (tmp_path / "escaped.fits").exists()


def test_an_interrupted_download_resumes_with_a_range_request(tmp_path, published):
    release, spec = published
    body = (release / spec.archive).read_bytes()
    home = tmp_path / "home"
    (home / ".downloads").mkdir(parents=True)
    (home / ".downloads" / (spec.archive + ".part")).write_bytes(body[:1000])
    seen = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Range"))
        start = int(request.headers["Range"].removeprefix("bytes=").rstrip("-"))
        return httpx.Response(206, content=body[start:])

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        target, fetched = fetch_bundle(
            "optical", source="https://mirror.invalid/data", bundles_dir=home,
            manifest={"optical": spec}, client=client,
        )
    assert seen == ["bytes=1000-"]
    assert fetched and (target / "a.fits").is_file()


def test_a_server_that_ignores_range_restarts_the_download(tmp_path, published):
    release, spec = published
    body = (release / spec.archive).read_bytes()
    home = tmp_path / "home"
    (home / ".downloads").mkdir(parents=True)
    (home / ".downloads" / (spec.archive + ".part")).write_bytes(b"stale" * 100)

    def serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        _, fetched = fetch_bundle("optical", source="https://mirror.invalid", bundles_dir=home,
                                  manifest={"optical": spec}, client=client)
    assert fetched


def test_a_bundle_is_never_written_into_the_package(tmp_path, published):
    release, spec = published
    for inside in (config.BUNDLED_DATA_DIR / "bundles", Path(bundles.__file__).parent / "x"):
        with pytest.raises(BundleError, match="installed package"):
            fetch_bundle("optical", source=str(release), bundles_dir=inside,
                         manifest={"optical": spec})


def test_an_unknown_bundle_names_the_known_ones(tmp_path, published):
    with pytest.raises(BundleError, match="choose from optical"):
        fetch_bundle("frames", bundles_dir=tmp_path, manifest={"optical": published[1]})


def test_fetch_data_is_a_kepler_mcp_subcommand(capsys):
    from tools.mcp.__main__ import main

    assert main(["fetch-data", "--list"]) == 0
    listed = capsys.readouterr().out
    assert "optical" in listed and "isochrones" in listed


# --- the guards, re-anchored -------------------------------------------------------


def test_the_bundled_data_root_is_the_repository_data_in_a_checkout():
    from tools.paths import is_checkout

    assert is_checkout()
    assert config.BUNDLED_DATA_DIR == (_REPO_ROOT / "data").resolve()


def test_the_fixture_guard_covers_fetched_bundles():
    from tools.wcs import _under_fixture_root

    assert _under_fixture_root(config.BUNDLES_DIR / "optical" / "m15.fits")
    assert _under_fixture_root(config.BUNDLED_DATA_DIR / "optical" / "m15.fits")
    assert not _under_fixture_root(config.KEPLER_HOME / "fits_downloads" / "hst.fits")


def test_the_kepler_owned_download_root_is_walked(tmp_path, monkeypatch):
    from tools.optical import _optical_data_roots

    home = tmp_path / "kepler"
    download = home / "fits_downloads"
    download.mkdir(parents=True)
    monkeypatch.setattr(config, "KEPLER_HOME", home)
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", download)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "site-packages" / "tools" / "_data")

    roots, warnings = _optical_data_roots()

    assert (download, True) in roots
    assert "download_root_outside_data_dir" not in [w.code for w in warnings]


def test_any_other_download_root_outside_the_data_dir_is_still_searched_flat(tmp_path, monkeypatch):
    from tools.optical import _optical_data_roots

    elsewhere = tmp_path / "mnt" / "archive"
    elsewhere.mkdir(parents=True)
    monkeypatch.setattr(config, "KEPLER_HOME", tmp_path / "kepler")
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", elsewhere)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")

    roots, warnings = _optical_data_roots()

    assert (elsewhere, False) in roots
    assert "download_root_outside_data_dir" in [w.code for w in warnings]


def test_a_missing_frame_library_says_so(tmp_path, monkeypatch):
    from tools.optical import list_optical_frames
    from tools.photometry import list_photometry_targets

    monkeypatch.delenv("KEPLER_OPTICAL_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "BUNDLED_DATA_DIR", tmp_path / "core")
    monkeypatch.setattr(config, "BUNDLES_DIR", tmp_path / "bundles")

    targets = list_photometry_targets()
    frames = list_optical_frames()

    assert targets.total_count == 0
    assert [w.code for w in targets.warnings] == ["bundle_not_installed"]
    assert "kepler-mcp fetch-data optical" in targets.warnings[0].message
    assert "bundle_not_installed" in [w.code for w in frames.warnings]
