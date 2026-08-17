"""Dark flat theme for the Tk demo.

Tk's defaults look like 1998, so every widget that shows is restyled. ttk's
'clam' engine is used as the base because it is the only built-in one that
honours background colour on most widget elements.

Every pixel measurement here is 20% below the original (SP-1.1-53). Font point
sizes are unchanged - `app.main()` drops the Tk scaling factor instead, which
shrinks all text by the same 20% in one place.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------

BG = "#14161a"          # window
SURFACE = "#1b1e24"     # panels
ELEVATED = "#23272f"    # inputs, cards
BORDER = "#2e333d"
BORDER_SOFT = "#262b33"

TEXT = "#e7eaf0"
TEXT_DIM = "#9aa3b2"
TEXT_FAINT = "#6b7382"

ACCENT = "#4c8dff"
ACCENT_HOVER = "#6ba0ff"
ACCENT_DIM = "#2f5db3"

OK = "#3ecf8e"
WARN = "#f0a836"
DANGER = "#ff6b6b"
NEUTRAL = "#6b7382"

STATUS_COLORS = {
    "CLASSIFIED": OK,
    "AMBIGUOUS": WARN,
    "UNCLASSIFIED": NEUTRAL,
    "ERROR": DANGER,
}


def pick_family(root: tk.Misc) -> tuple[str, str]:
    """Prefer the modern Windows UI font, fall back gracefully."""
    available = set(tkfont.families(root))
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue"):
        if candidate in available:
            ui = candidate
            break
    else:
        ui = "TkDefaultFont"
    for candidate in ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"):
        if candidate in available:
            mono = candidate
            break
    else:
        mono = "TkFixedFont"
    return ui, mono


class Fonts:
    def __init__(self, root: tk.Misc) -> None:
        ui, mono = pick_family(root)
        self.family = ui
        self.mono_family = mono
        self.body = tkfont.Font(root=root, family=ui, size=10)
        self.body_bold = tkfont.Font(root=root, family=ui, size=10, weight="bold")
        self.small = tkfont.Font(root=root, family=ui, size=9)
        self.tiny = tkfont.Font(root=root, family=ui, size=8)
        self.h1 = tkfont.Font(root=root, family=ui, size=15, weight="bold")
        self.h2 = tkfont.Font(root=root, family=ui, size=11, weight="bold")
        self.value = tkfont.Font(root=root, family=mono, size=10)
        self.mono = tkfont.Font(root=root, family=mono, size=9)


def apply_theme(root: tk.Tk) -> Fonts:
    fonts = Fonts(root)
    root.configure(bg=BG)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=TEXT, borderwidth=0,
                    focuscolor=BG, font=fonts.body)

    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Card.TFrame", background=ELEVATED)
    style.configure("Divider.TFrame", background=BORDER)

    style.configure("TLabel", background=BG, foreground=TEXT, font=fonts.body)
    style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Card.TLabel", background=ELEVATED, foreground=TEXT)
    style.configure("H1.TLabel", background=BG, foreground=TEXT, font=fonts.h1)
    style.configure("H2.TLabel", background=SURFACE, foreground=TEXT, font=fonts.h2)
    style.configure("Dim.TLabel", background=BG, foreground=TEXT_DIM, font=fonts.small)
    # Same label, greyed out: used for the half of the NEW row that is inactive.
    style.configure("Faint.TLabel", background=BG, foreground=TEXT_FAINT, font=fonts.small)
    style.configure("DimSurface.TLabel", background=SURFACE, foreground=TEXT_DIM,
                    font=fonts.small)
    style.configure("DimCard.TLabel", background=ELEVATED, foreground=TEXT_DIM,
                    font=fonts.small)
    style.configure("Concern.TLabel", background=ELEVATED, foreground=TEXT, font=fonts.h1)
    style.configure("Mono.TLabel", background=ELEVATED, foreground=TEXT, font=fonts.value)

    # ---- buttons ---------------------------------------------------------
    style.configure(
        "Accent.TButton",
        background=ACCENT, foreground="#ffffff", font=fonts.body_bold,
        padding=(14, 7), borderwidth=0, relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", ACCENT_DIM), ("active", ACCENT_HOVER), ("disabled", BORDER)],
        foreground=[("disabled", TEXT_FAINT)],
    )
    style.configure(
        "Ghost.TButton",
        background=ELEVATED, foreground=TEXT_DIM, font=fonts.body,
        padding=(11, 7), borderwidth=0, relief="flat",
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", BORDER), ("active", BORDER)],
        foreground=[("active", TEXT), ("disabled", TEXT_FAINT)],
    )

    # ---- entries / combobox ---------------------------------------------
    style.configure(
        "Dark.TEntry",
        fieldbackground=ELEVATED, background=ELEVATED, foreground=TEXT,
        insertcolor=ACCENT, borderwidth=0, relief="flat", padding=6,
    )
    style.configure(
        "Dark.TCombobox",
        fieldbackground=ELEVATED, background=ELEVATED, foreground=TEXT,
        arrowcolor=TEXT_DIM, borderwidth=0, relief="flat", padding=5,
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", ELEVATED)],
        foreground=[("readonly", TEXT)],
    )
    # The dropdown list is an OS-rendered popup; these options are the only
    # handle Tk gives us on it.
    root.option_add("*TCombobox*Listbox.background", ELEVATED)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", fonts.body)

    # ---- notebook --------------------------------------------------------
    style.configure("Dark.TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "Dark.TNotebook.Tab",
        background=BG, foreground=TEXT_FAINT, font=fonts.small,
        padding=(13, 7), borderwidth=0,
    )
    style.map(
        "Dark.TNotebook.Tab",
        background=[("selected", SURFACE)],
        foreground=[("selected", TEXT), ("active", TEXT_DIM)],
    )

    # ---- treeview --------------------------------------------------------
    style.configure(
        "Dark.Treeview",
        background=ELEVATED, fieldbackground=ELEVATED, foreground=TEXT,
        borderwidth=0, rowheight=22, font=fonts.body,
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=SURFACE, foreground=TEXT_DIM, font=fonts.tiny,
        relief="flat", padding=(6, 6),
    )
    style.map(
        "Dark.Treeview.Heading",
        background=[("active", SURFACE)],
    )
    style.map(
        "Dark.Treeview",
        background=[("selected", ACCENT_DIM)],
        foreground=[("selected", "#ffffff")],
    )

    # ---- scrollbar -------------------------------------------------------
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=SURFACE, troughcolor=BG, bordercolor=BG,
        arrowcolor=TEXT_FAINT, darkcolor=SURFACE, lightcolor=SURFACE,
        borderwidth=0, relief="flat", arrowsize=10,
    )
    style.map("Dark.Vertical.TScrollbar", background=[("active", BORDER)])

    style.configure("Dark.TPanedwindow", background=BG)
    style.configure("Dark.TSeparator", background=BORDER)

    return fonts


def text_widget(parent: tk.Misc, fonts: Fonts, *, mono: bool = False, **kw) -> tk.Text:
    """A Text widget that does not look like Tk."""
    opts = dict(
        bg=ELEVATED,
        fg=TEXT,
        insertbackground=ACCENT,
        selectbackground=ACCENT_DIM,
        selectforeground="#ffffff",
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER_SOFT,
        highlightcolor=ACCENT_DIM,
        padx=10,
        pady=8,
        wrap="word",
        font=fonts.mono if mono else fonts.body,
        undo=True,
    )
    opts.update(kw)
    return tk.Text(parent, **opts)


class Pill(tk.Canvas):
    """Rounded status chip. Tk has no rounded rectangle, so it is drawn."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, *, bg: str = ELEVATED) -> None:
        super().__init__(parent, height=19, width=104, bg=bg,
                         highlightthickness=0, borderwidth=0)
        self._fonts = fonts
        self._bg = bg

    def set(self, text: str, color: str) -> None:
        self.delete("all")
        f = self._fonts.tiny
        pad = 9
        w = f.measure(text) + pad * 2
        h = 18
        self.configure(width=w, height=h)
        r = h // 2
        # Rounded rect from two arcs plus a joining rectangle.
        self.create_oval(0, 0, r * 2, h, fill=color, outline=color)
        self.create_oval(w - r * 2, 0, w, h, fill=color, outline=color)
        self.create_rectangle(r, 0, w - r, h, fill=color, outline=color)
        self.create_text(w / 2, h / 2 + 1, text=text, fill="#0d0f13", font=f)


class Meter(tk.Canvas):
    """Flat confidence bar with threshold ticks."""

    HEIGHT = 6

    def __init__(self, parent: tk.Misc, *, width: int = 192, bg: str = ELEVATED) -> None:
        super().__init__(parent, height=self.HEIGHT, width=width, bg=bg,
                         highlightthickness=0, borderwidth=0)
        # NOT self._w -- that is Tkinter's internal widget path.
        self._track_width = width

    def set(self, fraction: float, color: str, *, ticks: tuple[float, ...] = ()) -> None:
        self.delete("all")
        w = self._track_width
        h = self.HEIGHT
        self.create_rectangle(0, 1, w, h - 1, fill=BORDER, outline=BORDER)
        filled = max(0.0, min(fraction, 1.0)) * w
        if filled > 0:
            self.create_rectangle(0, 1, filled, h - 1, fill=color, outline=color)
        for t in ticks:
            x = t * w
            self.create_line(x, 0, x, h, fill=TEXT_FAINT, width=1)
