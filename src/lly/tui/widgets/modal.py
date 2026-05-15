"""Shared base for every modal screen in lly.

Centralises the card chrome (rounded $primary border on $surface, centered,
80% wide capped at 110 cols) and the recurring helper classes (`title`,
`section-title`, `indent`, `button-row`). Three modals — detail, settings,
scan — used to duplicate ~30 lines of CSS each; they now inherit this.
"""

from __future__ import annotations

from textual.screen import ModalScreen


class LlyModalScreen[R](ModalScreen[R]):
    DEFAULT_CSS = """
    LlyModalScreen { align: center middle; }
    LlyModalScreen > .modal-card {
        background: $surface;
        border: round $primary;
        padding: 1 3;
        width: 80%;
        max-width: 110;
        height: auto;
    }
    LlyModalScreen .modal-title {
        text-style: bold;
        padding-bottom: 1;
        content-align: center middle;
        width: 100%;
    }
    LlyModalScreen .indent { padding-left: 2; }
    /* Container for action buttons. `height: auto` lets the row fit each
       Button (3 cells tall by default) plus padding — never use a fixed
       height here or buttons get clipped to a 1-row strip. */
    LlyModalScreen .button-row { padding: 1 0 1 2; height: auto; }
    LlyModalScreen .button-row Button { margin-right: 2; min-width: 18; }
    LlyModalScreen .modal-error { color: $error; padding-top: 1; padding-left: 2; }
    """
