"""Dark theme stylesheet for the PySide6 GUI."""

# Catppuccin Mocha-inspired palette — matches the Textual TUI aesthetic.
_BASE = "#1e1e2e"
_SURFACE = "#313244"
_OVERLAY = "#45475a"
_TEXT = "#cdd6f4"
_TEXT_MUTED = "#6c7086"
_ACCENT = "#89b4fa"
_ACCENT_DIM = "#74c7ec"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"

DARK_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────── */
QMainWindow, QWidget {{
    background-color: {_BASE};
    color: {_TEXT};
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: 14px;
}}

/* ── Sidebar ──────────────────────────────────────── */
QListWidget#sidebar {{
    background-color: {_SURFACE};
    border: none;
    border-right: 1px solid {_OVERLAY};
    outline: none;
    padding: 8px 0;
    font-size: 15px;
}}

QListWidget#sidebar::item {{
    padding: 14px 20px;
    color: {_TEXT_MUTED};
    border-left: 3px solid transparent;
}}

QListWidget#sidebar::item:selected {{
    background-color: {_BASE};
    color: {_ACCENT};
    border-left: 3px solid {_ACCENT};
    font-weight: bold;
}}

QListWidget#sidebar::item:hover:!selected {{
    background-color: {_OVERLAY};
    color: {_TEXT};
}}

/* ── Stacked content area ─────────────────────────── */
QStackedWidget {{
    background-color: {_BASE};
}}

/* ── Labels ───────────────────────────────────────── */
QLabel {{
    color: {_TEXT};
    background: transparent;
}}

QLabel#heading {{
    font-size: 22px;
    font-weight: bold;
    color: {_ACCENT};
}}

QLabel#subheading {{
    font-size: 14px;
    color: {_TEXT_MUTED};
}}

/* ── Buttons ──────────────────────────────────────── */
QPushButton {{
    background-color: {_SURFACE};
    color: {_TEXT};
    border: 1px solid {_OVERLAY};
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 14px;
}}

QPushButton:hover {{
    background-color: {_OVERLAY};
    border-color: {_ACCENT};
}}

QPushButton:pressed {{
    background-color: {_ACCENT};
    color: {_BASE};
}}

/* ── Input fields ─────────────────────────────────── */
QLineEdit {{
    background-color: {_SURFACE};
    color: {_TEXT};
    border: 1px solid {_OVERLAY};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 14px;
    selection-background-color: {_ACCENT};
    selection-color: {_BASE};
}}

QLineEdit:focus {{
    border-color: {_ACCENT};
}}

/* ── Scrollbars ───────────────────────────────────── */
QScrollBar:vertical {{
    background: {_SURFACE};
    width: 10px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {_OVERLAY};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {_TEXT_MUTED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
