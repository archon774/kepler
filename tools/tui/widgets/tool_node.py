"""One collapsible transcript node for a model-requested tool call."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static

__all__ = ["ToolNode"]


class ToolNode(Static):
    """Render a proposed, running, finished, or denied tool call."""

    def __init__(
        self, call_id: str, name: str, arguments: Mapping[str, Any]
    ) -> None:
        super().__init__()
        self.call_id = call_id
        self.tool_name = name
        self.arguments = dict(arguments)
        self.state = "proposed"
        self.cache_hit = False
        self.result: dict[str, Any] | None = None
        self.artifacts: tuple[str, ...] = ()
        self.duration_ms: float | None = None
        self.reason: str | None = None
        self.expanded = False
        self._started_at: float | None = None
        self._refresh()

    def on_mount(self) -> None:
        """Keep a running call visibly alive without touching the engine."""

        self.set_interval(0.25, self._refresh_running_duration)

    def on_click(self) -> None:
        """Expand or collapse the full arguments and result details."""

        self.expanded = not self.expanded
        self._refresh()

    def start(self, cache_hit: bool) -> None:
        """Mark the call running and begin its elapsed-time display."""

        self.state = "running"
        self.cache_hit = cache_hit
        self._started_at = time.monotonic()
        self._refresh()

    def finish(
        self,
        result: Mapping[str, Any],
        artifacts: tuple[str, ...],
        duration_ms: float | None,
    ) -> None:
        """Record a completed result and its written artifacts."""

        self.state = "finished"
        self.result = dict(result)
        self.artifacts = tuple(artifacts)
        self.duration_ms = duration_ms
        self._refresh()

    def deny(self, reason: str) -> None:
        """Render a policy denial without pretending the call ran."""

        self.state = "denied"
        self.reason = reason
        self._refresh()

    def _refresh_running_duration(self) -> None:
        if self.state == "running":
            self._refresh()

    def _refresh(self) -> None:
        self.update(self._render_content())

    def _render_content(self) -> RenderableType:
        status, details = self._summary()
        header = Text(f"{status} {self.tool_name}{details}")
        if not self.expanded:
            return header

        parts: list[RenderableType] = [header, Text("Arguments:")]
        parts.append(Syntax(json.dumps(self.arguments, indent=2, default=str), "json"))
        if self.result is not None:
            parts.extend(
                [
                    Text("Result:"),
                    Syntax(json.dumps(self.result, indent=2, default=str), "json"),
                ]
            )
        if self.artifacts:
            parts.append(Text("Artifacts: " + ", ".join(self.artifacts)))
        if self.reason:
            parts.append(Text("Reason: " + self.reason))
        return Group(*parts)

    def _summary(self) -> tuple[str, str]:
        if self.state == "running":
            return "⠋", f" (running {self._elapsed_ms():.0f} ms)"
        if self.state == "finished":
            marker = "[cached]" if self.cache_hit else ""
            duration = "" if self.duration_ms is None else f" ({self.duration_ms:.0f} ms)"
            return "✓", f" {marker}{duration}"
        if self.state == "denied":
            return "✗", " (denied)"
        return "…", " (proposed)"

    def _elapsed_ms(self) -> float:
        if self._started_at is None:
            return 0.0
        return (time.monotonic() - self._started_at) * 1000.0
