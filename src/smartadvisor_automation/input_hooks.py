"""Low-level Windows input hooks for the action recorder.

The hook callbacks run on a dedicated thread with its own message pump and
do nothing but append a tuple to a queue. That is deliberate: Windows
silently unhooks a low-level hook whose callback exceeds
`LowLevelHooksTimeout` (300 ms by default), and a slow callback delays
input for the whole desktop - including SmartAdvisor. Every expensive
step, above all UIA resolution, happens on the Tk thread that drains the
queue.

Nothing here inspects typed characters beyond classifying them. Character
keys are reported as `("char", ...)` without the character; only
structural keys and modifier chords carry an identity.
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from typing import Any

user32 = ctypes.windll.user32

# LRESULT/LPARAM must be pointer-sized: c_ssize_t is correct on both the
# x86 shipping target and an x64 dev machine. wintypes.LPARAM is not, and
# gets the CallNextHookEx round-trip wrong (OverflowError per event, which
# a --windowed build swallows silently).
LRESULT = ctypes.c_ssize_t
LPARAM = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, LPARAM
)

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    LPARAM,
]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

MOUSE_BUTTONS = {
    WM_LBUTTONDOWN: "left",
    WM_RBUTTONDOWN: "right",
    WM_MBUTTONDOWN: "middle",
}

# pywinauto type_keys() names, so a recorded chord can be replayed as-is.
NAMED_KEYS = {
    0x08: "{BACKSPACE}",
    0x09: "{TAB}",
    0x0D: "{ENTER}",
    0x1B: "{ESC}",
    0x21: "{PGUP}",
    0x22: "{PGDN}",
    0x23: "{END}",
    0x24: "{HOME}",
    0x25: "{LEFT}",
    0x26: "{UP}",
    0x27: "{RIGHT}",
    0x28: "{DOWN}",
    0x2D: "{INSERT}",
    0x2E: "{DELETE}",
    0x70: "{F1}",
    0x71: "{F2}",
    0x72: "{F3}",
    0x73: "{F4}",
    0x74: "{F5}",
    0x75: "{F6}",
    0x76: "{F7}",
    0x77: "{F8}",
    0x78: "{F9}",
    0x79: "{F10}",
    0x7A: "{F11}",
    0x7B: "{F12}",
}

CTRL_PREFIX = "^"
ALT_PREFIX = "%"
SHIFT_PREFIX = "+"


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ssize_t),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ssize_t),
    ]


def is_character_key(vk: int) -> bool:
    """Report whether a virtual key produces a text character.

    Character keys are the ones whose value could be part of a field
    value, so the recorder never stores their identity.
    """

    if vk in NAMED_KEYS:
        return False
    if 0x30 <= vk <= 0x39:
        return True
    if 0x41 <= vk <= 0x5A:
        return True
    if 0x60 <= vk <= 0x69:
        return True
    if vk in {0x6A, 0x6B, 0x6D, 0x6E, 0x6F}:
        return True
    if 0xBA <= vk <= 0xC0:
        return True
    if 0xDB <= vk <= 0xDF:
        return True
    return vk == 0x20


def chord_keys(
    vk: int, *, ctrl: bool = False, alt: bool = False, shift: bool = False
) -> str | None:
    """Return the type_keys() form of a structural key press.

    Returns None for plain data entry - an unmodified character key, or a
    shifted one - because those belong to a field value and are never
    recorded. A character key held with Ctrl or Alt is an accelerator
    (`^o`), not data, so it is safe and useful to record.
    """

    named = NAMED_KEYS.get(vk)
    if named is None:
        if not (ctrl or alt):
            return None
        if not is_character_key(vk):
            return None
        if 0x41 <= vk <= 0x5A:
            named = chr(vk).lower()
        elif 0x30 <= vk <= 0x39:
            named = chr(vk)
        else:
            return None

    prefix = ""
    if ctrl:
        prefix += CTRL_PREFIX
    if alt:
        prefix += ALT_PREFIX
    if shift:
        prefix += SHIFT_PREFIX
    return f"{prefix}{named}"


def _modifier_state() -> tuple[bool, bool, bool]:
    """Read Ctrl/Alt/Shift. A plain syscall, safe inside the callback."""

    def down(key: int) -> bool:
        return bool(user32.GetAsyncKeyState(key) & 0x8000)

    return down(VK_CONTROL), down(VK_MENU), down(VK_SHIFT)


class InputHookListener:
    """Run low-level mouse and keyboard hooks on a private thread.

    Raw events are pushed onto `events` as tuples:

    - `("click", button, x, y, monotonic)` on mouse button down;
    - `("chord", keys, monotonic)` for a structural key or accelerator;
    - `("char", monotonic)` for a character key, with no identity.

    `start()` is safe to call once; `stop()` unhooks and joins.
    """

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.error_code: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Both HOOKPROC objects must stay referenced for the process's
        # lifetime; if either is collected the next event crashes us.
        self._mouse_proc = HOOKPROC(self._on_mouse)
        self._keyboard_proc = HOOKPROC(self._on_keyboard)

    def _on_mouse(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code == 0:
                button = MOUSE_BUTTONS.get(int(wparam))
                if button is not None:
                    data = ctypes.cast(
                        lparam, ctypes.POINTER(MSLLHOOKSTRUCT)
                    ).contents
                    self.events.put(
                        (
                            "click",
                            button,
                            int(data.pt.x),
                            int(data.pt.y),
                            time.monotonic(),
                        )
                    )
        except Exception:
            # A raising callback is swallowed by ctypes and invisible in a
            # --windowed build; never let it reach the hook chain.
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_keyboard(self, code: int, wparam: int, lparam: int) -> int:
        try:
            if code == 0 and int(wparam) in {WM_KEYDOWN, WM_SYSKEYDOWN}:
                data = ctypes.cast(
                    lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)
                ).contents
                vk = int(data.vkCode)
                if vk not in {VK_SHIFT, VK_CONTROL, VK_MENU}:
                    ctrl, alt, shift = _modifier_state()
                    keys = chord_keys(vk, ctrl=ctrl, alt=alt, shift=shift)
                    now = time.monotonic()
                    if keys is not None:
                        self.events.put(("chord", keys, now))
                    elif is_character_key(vk) and not (ctrl or alt):
                        self.events.put(("char", now))
                    # Anything else is a key with no replayable name and
                    # no text contribution (media keys, F13+): ignored
                    # rather than mistaken for typing.
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self) -> None:
        mouse_handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, None, 0
        )
        keyboard_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._keyboard_proc, None, 0
        )
        if not mouse_handle or not keyboard_handle:
            self.error_code = (
                f"set_hook_failed_{ctypes.get_last_error()}"
            )
            self._stop.set()

        message = wintypes.MSG()
        while not self._stop.is_set():
            if user32.PeekMessageW(
                ctypes.byref(message), None, 0, 0, 0x0001
            ):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            else:
                time.sleep(0.005)

        for handle in (mouse_handle, keyboard_handle):
            if handle:
                user32.UnhookWindowsHookEx(handle)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="input-hooks", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)

    def drain(self) -> list[tuple[Any, ...]]:
        """Take every queued event without blocking."""

        drained: list[tuple[Any, ...]] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained
