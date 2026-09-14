# TUI Artifact Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Kepler TUI a deterministic, CI-tested artifact browser with terminal image and WAV previews.

**Architecture:** Keep capability probing and the two renderers framework-free under `tools/tui/render/`. `ArtifactBrowser` consumes the existing `tools.workspace.list_artifacts` metadata API, selects a renderer by the cached app graphics tier, and leaves tool and engine packages untouched.

**Tech Stack:** Python 3.12+, Pillow, Rich, Textual 8.2.8, textual-image 0.13.2, pytest.

**Spec:** `docs/working/tui-harness.md` sections 7, 9, 10, and Phase E.

## Global Constraints

- `tools/agent/` remains UI- and Rich-free; Phase E changes only `tools/tui/` and its tests/fixture.
- `detect_tier` runs once at application startup and records `KITTY`, `ITERM2`, `SIXEL`, or `HALFBLOCK`.
- The Sixel probe uses a short device-attributes timeout; environment detection has priority over the probe.
- Pillow half-block rendering is the universal path and must be deterministic against a committed 4×4 PNG.
- Native image tiers use `textual-image`; every artifact view keeps a readable filesystem path.
- The WAV waveform is presentational only: Kepler sonification ignores source timestamps, so it cannot support a scientific period measurement.
- Default tests are offline and deterministic; do not launch an external viewer in tests.

---

### Task 1: Terminal graphics capability model

**Files:**
- Create: `tools/tui/render/__init__.py`
- Create: `tools/tui/render/capability.py`
- Create: `tests/test_tui_render_capability.py`

**Interfaces:**
- Produces: `GraphicsTier(str, Enum)` with `KITTY`, `ITERM2`, `SIXEL`, `HALFBLOCK` members.
- Produces: `detect_tier(environ: Mapping[str, str] | None = None, *, sixel_probe: Callable[[], bool] = _probe_sixel) -> GraphicsTier`.

- [ ] **Step 1: Write the failing tests**

```python
def test_detect_tier_prefers_kitty_environment_over_other_signals():
    assert detect_tier(
        {"KITTY_WINDOW_ID": "42", "TERM": "xterm-kitty"},
        sixel_probe=lambda: True,
    ) is GraphicsTier.KITTY


def test_detect_tier_uses_sixel_only_after_kitty_and_iterm2_checks():
    assert detect_tier(
        {"TERM_PROGRAM": "iTerm.app"}, sixel_probe=lambda: True
    ) is GraphicsTier.ITERM2
    assert detect_tier({}, sixel_probe=lambda: True) is GraphicsTier.SIXEL
    assert detect_tier({}, sixel_probe=lambda: False) is GraphicsTier.HALFBLOCK
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_render_capability.py -v`

Expected: FAIL because `tools.tui.render.capability` does not exist.

- [ ] **Step 3: Write the minimal capability implementation**

```python
class GraphicsTier(str, Enum):
    KITTY = "kitty"
    ITERM2 = "iterm2"
    SIXEL = "sixel"
    HALFBLOCK = "halfblock"


def detect_tier(environ=None, *, sixel_probe=_probe_sixel) -> GraphicsTier:
    values = os.environ if environ is None else environ
    if values.get("KITTY_WINDOW_ID") or values.get("TERM") == "xterm-kitty":
        return GraphicsTier.KITTY
    if values.get("TERM_PROGRAM") == "iTerm.app":
        return GraphicsTier.ITERM2
    return GraphicsTier.SIXEL if sixel_probe() else GraphicsTier.HALFBLOCK
```

`_probe_sixel` delegates to `textual_image.renderable.sixel.query_terminal_support`, whose 0.1-second device-attributes timeout meets the design contract.

- [ ] **Step 4: Run the focused capability tests**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_render_capability.py -v`

Expected: PASS.

### Task 2: Deterministic visual and audio fallback renderers

**Files:**
- Create: `tools/tui/render/image.py`
- Create: `tools/tui/render/waveform.py`
- Create: `tests/fixtures/tui/four_by_four.png`
- Create: `tests/test_tui_render_image.py`
- Create: `tests/test_tui_render_waveform.py`

**Interfaces:**
- Consumes: a local PNG path and optional `max_width`.
- Produces: `render_halfblocks(path: str | Path, *, max_width: int = 80) -> rich.text.Text`.
- Consumes: PCM WAV path and optional character width.
- Produces: `render_waveform(path: str | Path, *, width: int = 60) -> rich.text.Text`.

- [ ] **Step 1: Write the failing renderer tests**

```python
def test_halfblocks_match_the_committed_four_by_four_png_golden():
    rendered = render_halfblocks(FIXTURE, max_width=4)
    assert _ansi(rendered) == (
        "\x1b[38;2;255;0;0;48;2;0;0;0m▀\x1b[0m"
        "\x1b[38;2;0;255;0;48;2;128;128;128m▀\x1b[0m"
        "\x1b[38;2;0;0;255;48;2;255;255;0m▀\x1b[0m"
        "\x1b[38;2;255;255;255;48;2;0;255;255m▀\x1b[0m\n"
        "\x1b[38;2;255;0;255;48;2;32;32;32m▀\x1b[0m"
        "\x1b[38;2;255;128;0;48;2;64;64;64m▀\x1b[0m"
        "\x1b[38;2;0;128;255;48;2;96;96;96m▀\x1b[0m"
        "\x1b[38;2;128;0;255;48;2;128;128;128m▀\x1b[0m"
    )


def test_waveform_renders_stereo_pcm_as_a_braille_preview(tmp_path):
    wav_path = _write_stereo_wav(tmp_path / "pulse.wav", [-32768, 32767])
    assert "\u2800" < render_waveform(wav_path, width=1).plain <= "\u28ff"
```

- [ ] **Step 2: Run the renderer tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_render_image.py tests/test_tui_render_waveform.py -v`

Expected: FAIL because the render modules and committed fixture are absent.

- [ ] **Step 3: Create the fixture and minimal renderers**

Create `four_by_four.png` from this exact top-to-bottom RGB grid, so its expected
ANSI result is unambiguous:

```python
PIXELS = [
    [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)],
    [(0, 0, 0), (128, 128, 128), (255, 255, 0), (0, 255, 255)],
    [(255, 0, 255), (255, 128, 0), (0, 128, 255), (128, 0, 255)],
    [(32, 32, 32), (64, 64, 64), (96, 96, 96), (128, 128, 128)],
]
```

Implement the fallback renderer with one `▀` that gives its top pixel Rich's
foreground color and its bottom pixel Rich's background color. It composites
transparency on black, downsizes only when `max_width` requires it, and appends
a black lower row for an odd source height:

```python
def render_halfblocks(path: str | Path, *, max_width: int = 80) -> Text:
    if max_width < 1:
        raise ValueError("max_width must be positive")
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
    image = _composite_on_black(rgba)
    image = _resize_to_width(image, max_width)
    image = _pad_even_height(image)
    return _halfblock_text(image)
```

`render_waveform` reads PCM frames with the standard `wave` module, averages
channels into one normalized stream, reduces it to two values per braille cell,
and sets the matching 2×4 dots. Its module docstring states that the time axis
is sample index and cannot be used to infer a pulsar period.

- [ ] **Step 4: Run the focused renderer tests**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_render_image.py tests/test_tui_render_waveform.py -v`

Expected: PASS with exact ANSI output for the PNG fixture.

### Task 3: Artifact browser and application wiring

**Files:**
- Create: `tools/tui/widgets/artifacts.py`
- Modify: `tools/tui/app.py`
- Modify: `tests/test_tui_app.py`
- Create: `tests/test_tui_artifacts.py`

**Interfaces:**
- Consumes: `tools.workspace.list_artifacts() -> list[ArtifactMetadata]`, `GraphicsTier`, `render_halfblocks`, and `render_waveform`.
- Produces: `ArtifactBrowser(ModalScreen[None])` with a visible path, keyboard dismissal, a selected preview, and an explicit open-externally action.
- Produces: `KeplerApp.graphics_tier` cached once at construction, `show_artifacts(args)` command handler, and `F3` browser binding.

- [ ] **Step 1: Write failing artifact-browser and app tests**

```python
def test_artifact_browser_lists_metadata_and_keeps_the_path_visible(tmp_path):
    path = tmp_path / "result.txt"
    path.write_text("result", encoding="utf-8")
    browser = ArtifactBrowser([describe_artifact_file(path)])
    app = KeplerApp(backend=object())
    async with app.run_test() as pilot:
        app.push_screen(browser)
        await pilot.pause()
        assert str(path) in str(browser.query_one("#artifact-path").render())


def test_artifacts_command_opens_the_modal_without_starting_the_engine():
    app = KeplerApp(backend=object())
    async with app.run_test() as pilot:
        await pilot.press("/", "a", "enter")
        await pilot.pause()
        assert isinstance(app.screen, ArtifactBrowser)
        assert app.engine_starts == 0
```

- [ ] **Step 2: Run the browser tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_artifacts.py tests/test_tui_app.py -v`

Expected: FAIL because `ArtifactBrowser` and the handler do not exist.

- [ ] **Step 3: Write the minimal browser and app integration**

Use an `OptionList` of `ArtifactMetadata` labels. Highlight changes update a
path `Static` and replace the preview child with `textual_image.widget.Image`
for native image tiers, `render_halfblocks` for image fallback, or
`render_waveform` for WAV. Other artifact types retain metadata and path. Bind
`escape` to dismiss and `o` to an injected `webbrowser.open` helper:

```python
def open_externally(path: str | Path) -> bool:
    return webbrowser.open(Path(path).expanduser().resolve().as_uri())


def show_preview(self, artifact: ArtifactMetadata) -> None:
    self.query_one("#artifact-path", Static).update(artifact.file.path)
    preview = self.query_one("#artifact-preview", Vertical)
    preview.remove_children()
    preview.mount(_preview_widget(artifact, self.tier))
```

Add `F3` and `/artifacts` to `KeplerApp`; cache `detect_tier()` in `__init__`
and show the tier in `_status_text`.

- [ ] **Step 4: Run the focused TUI tests**

Run: `UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_app.py tests/test_tui_artifacts.py tests/test_tui_render_capability.py tests/test_tui_render_image.py tests/test_tui_render_waveform.py -v`

Expected: PASS.

### Task 4: Phase verification

**Files:**
- Modify: the files produced by Tasks 1–3 only if verification identifies a Phase E defect.

**Interfaces:**
- Verifies: Phase E’s detection, fallback renderer, native renderer selection, waveform disclaimer, modal browser, F3, and `/artifacts` contracts.

- [ ] **Step 1: Run formatting and focused checks**

Run: `git diff --check && UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest tests/test_tui_app.py tests/test_tui_artifacts.py tests/test_tui_render_capability.py tests/test_tui_render_image.py tests/test_tui_render_waveform.py -v`

Expected: clean diff check and every focused test passing.

- [ ] **Step 2: Run the project verification commands**

Run: `python3 -m compileall tools algorithms && UV_CACHE_DIR=/tmp/kepler-uv-cache uv run pytest && git diff --check`

Expected: syntax smoke test succeeds, default offline suite succeeds, and the patch has no whitespace errors.

- [ ] **Step 3: Inspect Phase E coverage before handoff**

Verify that the fixture is tracked, the app caches one graphics tier, `/artifacts` and F3 both open the modal, each preview leaves its filesystem path visible, image preview selection uses `textual-image` for a non-fallback tier, and `render_waveform` documents its non-scientific purpose.
