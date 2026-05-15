"""Reusable layout primitives used by every modal in the app."""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical
from textual.widgets import Label


class Section(Vertical):
    """A titled card section.

    Renders a bold accent-coloured title followed by whatever children the
    caller passes in. Pure layout: every modal in lly stacks these to get
    consistent visual rhythm (Device info, State, Controls, …).

    Usage:

        with Section("Controls"):
            with Horizontal(classes="button-row"):
                yield Button("Open (o)", id="open")
    """

    DEFAULT_CSS = """
    Section { height: auto; }
    Section > .section-title {
        text-style: bold;
        color: $accent;
        padding-top: 1;
        padding-bottom: 1;
    }
    """

    def __init__(self, title: str, **kwargs: Any) -> None:
        # Title is the first child so it renders above the body content
        # whether the caller uses `Section("X", body)` or `with Section("X"):`.
        super().__init__(Label(title, classes="section-title"), **kwargs)
