"""Terminal graphics capability detection for the Kepler TUI."""

from __future__ import annotations


class _NonTerminal:
    """A stream-like object that must never receive a device query."""

    def isatty(self) -> bool:
        return False


def test_detect_tier_prefers_kitty_environment_over_sixel_probe():
    """An available Sixel probe must not downgrade a Kitty terminal."""

    from tools.tui.render.capability import GraphicsTier, detect_tier

    tier = detect_tier(
        {"KITTY_WINDOW_ID": "42", "TERM": "xterm-kitty"},
        sixel_probe=lambda: True,
    )

    assert tier is GraphicsTier.KITTY


def test_detect_tier_recognizes_iterm_before_sixel_probe():
    """iTerm's declared protocol tier has priority over a generic probe."""

    from tools.tui.render.capability import GraphicsTier, detect_tier

    tier = detect_tier({"TERM_PROGRAM": "iTerm.app"}, sixel_probe=lambda: True)

    assert tier is GraphicsTier.ITERM2


def test_detect_tier_uses_sixel_or_halfblocks_when_no_environment_matches():
    """An ordinary terminal uses Sixel when available and has a usable floor."""

    from tools.tui.render.capability import GraphicsTier, detect_tier

    assert detect_tier({}, sixel_probe=lambda: True) is GraphicsTier.SIXEL
    assert detect_tier({}, sixel_probe=lambda: False) is GraphicsTier.HALFBLOCK


def test_detect_tier_skips_device_queries_when_standard_streams_are_not_terminals(
    monkeypatch,
):
    """Headless tests and redirected launchers must use the text fallback safely."""

    from tools.tui.render import capability

    monkeypatch.setattr(capability.sys, "__stdin__", _NonTerminal())
    monkeypatch.setattr(capability.sys, "__stdout__", _NonTerminal())

    assert capability.detect_tier({}) is capability.GraphicsTier.HALFBLOCK
