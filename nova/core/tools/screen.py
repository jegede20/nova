"""Screen understanding and input control.

Nova prefers Windows UI Automation (accessibility tree) to find controls by name
and only falls back to vision coordinates when the element can't be resolved.
It never clicks coordinates the model invented out of thin air.
"""

from __future__ import annotations

import time
from typing import Any

from ..logging_setup import get_logger
from ..paths import IS_WINDOWS, screenshots_dir
from .registry import ToolResult, registry

log = get_logger("tools.screen")

_vision_hook: Any = None      # set by NovaCore: async fn(image_path, question) -> str


def set_vision_hook(fn: Any) -> None:
    global _vision_hook
    _vision_hook = fn


def _pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True          # slam mouse to a corner to abort
        pyautogui.PAUSE = 0.06
        return pyautogui
    except Exception as e:
        log.warning("pyautogui unavailable: %s", e)
        return None


def _uia():
    if not IS_WINDOWS:
        return None
    try:
        import uiautomation

        return uiautomation
    except Exception:
        return None


@registry.tool(
    "take_screenshot",
    "Capture the current screen to an image file. Use before read_screen or before clicking something you must locate.",
    {"region": {"type": "string", "description": "Optional 'left,top,width,height' region"}},
    category="screen",
)
def take_screenshot(region: str = "") -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Screen capture isn't available - pyautogui or a display is missing.")
    box = None
    if region:
        try:
            parts = [int(x) for x in region.split(",")]
            if len(parts) == 4:
                box = tuple(parts)
        except ValueError:
            return ToolResult.fail("The region should look like 'left,top,width,height'.")
    path = screenshots_dir() / f"screen_{int(time.time())}.png"
    try:
        img = pg.screenshot(region=box) if box else pg.screenshot()
        img.save(str(path))
    except Exception as e:
        return ToolResult.fail(f"I couldn't capture the screen: {e}")
    _prune_screenshots()
    return ToolResult.success("Captured the screen.", path=str(path),
                              size=f"{img.width}x{img.height}")


def _prune_screenshots(keep: int = 12) -> None:
    try:
        shots = sorted(screenshots_dir().glob("screen_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in shots[keep:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


@registry.tool(
    "read_screen",
    "Look at the current screen and answer a question about it, e.g. 'what is on my screen' or 'where is the Settings button'.",
    {"question": {"type": "string", "description": "What to find out about the screen",
                  "default": "Describe what is currently on screen and list the main clickable controls."}},
    category="screen",
    requires_llm=True,
)
async def read_screen(question: str = "Describe what is currently on screen.") -> ToolResult:
    shot = take_screenshot()
    if not shot.ok:
        return shot
    path = shot.data["path"]

    # Accessibility info first: cheaper, more precise, stays local.
    elements = _list_ui_elements()
    if _vision_hook is None:
        if elements:
            names = ", ".join(e["name"] for e in elements[:12])
            return ToolResult.success(f"Visible controls: {names}", elements=elements, path=path)
        return ToolResult.fail("Screen understanding needs a vision-capable AI provider, which isn't configured.")

    hint = ""
    if elements:
        hint = "\nKnown UI elements from the accessibility tree: " + \
               "; ".join(f"{e['name']} ({e['type']})" for e in elements[:25])
    try:
        answer = await _vision_hook(path, question + hint)
    except Exception as e:
        return ToolResult.fail(f"I couldn't analyse the screen: {e}")
    return ToolResult.success(answer or "I couldn't tell what's on screen.", path=path, elements=elements[:25])


def _list_ui_elements(limit: int = 60) -> list[dict]:
    """Read the foreground window's accessibility tree (Windows only)."""
    auto = _uia()
    if auto is None:
        return []
    out: list[dict] = []
    try:
        window = auto.GetForegroundControl()
        for ctrl, _depth in auto.WalkControl(window, includeTop=True, maxDepth=6):
            if len(out) >= limit:
                break
            name = (ctrl.Name or "").strip()
            ctype = ctrl.ControlTypeName.replace("Control", "")
            if not name or ctype not in {"Button", "Edit", "Hyperlink", "MenuItem", "CheckBox",
                                         "RadioButton", "Tab", "TabItem", "ListItem", "ComboBox", "Text"}:
                continue
            try:
                rect = ctrl.BoundingRectangle
                if rect.width() <= 0:
                    continue
                out.append({"name": name[:60], "type": ctype,
                            "x": rect.xcenter(), "y": rect.ycenter()})
            except Exception:
                continue
    except Exception as e:
        log.debug("UI automation unavailable: %s", e)
    return out


def find_element(label: str) -> dict | None:
    needle = label.lower().strip()
    elements = _list_ui_elements(120)
    for e in elements:
        if e["name"].lower() == needle:
            return e
    for e in elements:
        if needle in e["name"].lower():
            return e
    return None


@registry.tool(
    "list_screen_elements",
    "List the named buttons, links and fields in the active window using Windows accessibility data.",
    {},
    category="screen",
)
def list_screen_elements() -> ToolResult:
    elements = _list_ui_elements()
    if not elements:
        return ToolResult(False, "I couldn't read any named controls from the active window.", {"elements": []})
    return ToolResult.success(f"I can see {len(elements)} controls.", elements=elements)


@registry.tool(
    "click",
    "Click a UI control. Prefer 'label' so Nova finds the control by name; only use x/y from a screen reading.",
    {"label": {"type": "string", "description": "Visible name of the button/link to click"},
     "x": {"type": "integer", "description": "Screen X, only if the label cannot be used"},
     "y": {"type": "integer", "description": "Screen Y, only if the label cannot be used"},
     "button": {"type": "string", "description": "left or right", "enum": ["left", "right"], "default": "left"},
     "double": {"type": "boolean", "description": "Double-click", "default": False}},
    category="input",
)
def click(label: str = "", x: int = 0, y: int = 0, button: str = "left", double: bool = False) -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Mouse control isn't available on this machine.")

    target_x, target_y, how = x, y, "coordinates"
    if label:
        found = find_element(label)
        if found:
            target_x, target_y, how = int(found["x"]), int(found["y"]), "accessibility"
        elif not (x or y):
            return ToolResult.fail(
                f"I couldn't find a control called '{label}' in the active window. "
                "Ask me to read the screen first."
            )
    if not (target_x or target_y):
        return ToolResult.fail("I need either a control name or a position to click.")

    width, height = pg.size()
    if not (0 <= target_x <= width and 0 <= target_y <= height):
        return ToolResult.fail("That click position is outside the screen.")

    try:
        pg.moveTo(target_x, target_y, duration=0.15)
        if double:
            pg.doubleClick()
        else:
            pg.click(button=button)
    except Exception as e:
        return ToolResult.fail(f"The click failed: {e}")
    what = f"'{label}'" if label else f"({target_x}, {target_y})"
    return ToolResult.success(f"Clicked {what}.", x=target_x, y=target_y, method=how)


@registry.tool(
    "double_click",
    "Double-click a control or position.",
    {"label": {"type": "string", "description": "Control name"},
     "x": {"type": "integer", "description": "Screen X"},
     "y": {"type": "integer", "description": "Screen Y"}},
    category="input",
)
def double_click(label: str = "", x: int = 0, y: int = 0) -> ToolResult:
    return click(label=label, x=x, y=y, double=True)


@registry.tool(
    "right_click",
    "Right-click a control or position to open its context menu.",
    {"label": {"type": "string", "description": "Control name"},
     "x": {"type": "integer", "description": "Screen X"},
     "y": {"type": "integer", "description": "Screen Y"}},
    category="input",
)
def right_click(label: str = "", x: int = 0, y: int = 0) -> ToolResult:
    return click(label=label, x=x, y=y, button="right")


@registry.tool(
    "type_text",
    "Type text into the focused field.",
    {"text": {"type": "string", "description": "Text to type", "required": True},
     "press_enter": {"type": "boolean", "description": "Press Enter afterwards", "default": False}},
    category="input",
)
def type_text(text: str, press_enter: bool = False) -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Keyboard control isn't available on this machine.")
    try:
        pg.typewrite(text, interval=0.012)
        if press_enter:
            pg.press("enter")
    except Exception as e:
        return ToolResult.fail(f"I couldn't type that: {e}")
    return ToolResult.success(f"Typed {len(text)} characters.", length=len(text))


ALLOWED_KEYS = {
    "enter", "tab", "esc", "escape", "space", "backspace", "delete", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "f1", "f2", "f3", "f4", "f5", "f6", "f11", "f12",
    "ctrl", "alt", "shift", "win", "a", "c", "v", "x", "z", "y", "s", "f", "n", "t", "w", "r", "p", "l",
}


@registry.tool(
    "press_key",
    "Press a key or keyboard shortcut, e.g. 'enter', 'ctrl+c', 'alt+tab', 'win+e'.",
    {"keys": {"type": "string", "description": "Key or combination like ctrl+c", "required": True}},
    category="input",
)
def press_key(keys: str) -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Keyboard control isn't available on this machine.")
    parts = [k.strip().lower() for k in keys.replace(" ", "").split("+") if k.strip()]
    if not parts:
        return ToolResult.fail("I didn't understand that key combination.")
    unknown = [k for k in parts if k not in ALLOWED_KEYS]
    if unknown:
        return ToolResult.fail(f"I'm not allowed to press: {', '.join(unknown)}.")
    # Guard against dangerous combos
    combo = "+".join(parts)
    if combo in {"ctrl+alt+delete", "alt+f4"}:
        return ToolResult.fail(f"I won't press {combo} automatically.")
    try:
        if len(parts) == 1:
            pg.press(parts[0])
        else:
            pg.hotkey(*parts)
    except Exception as e:
        return ToolResult.fail(f"I couldn't press those keys: {e}")
    return ToolResult.success(f"Pressed {combo}.", keys=combo)


@registry.tool(
    "scroll",
    "Scroll the active window up or down.",
    {"direction": {"type": "string", "description": "up or down", "enum": ["up", "down"], "default": "down"},
     "amount": {"type": "integer", "description": "How many notches", "default": 5}},
    category="input",
)
def scroll(direction: str = "down", amount: int = 5) -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Scrolling isn't available on this machine.")
    clicks = max(1, min(30, amount)) * 120
    try:
        pg.scroll(clicks if direction == "up" else -clicks)
    except Exception as e:
        return ToolResult.fail(f"I couldn't scroll: {e}")
    return ToolResult.success(f"Scrolled {direction}.")


@registry.tool(
    "copy_selection",
    "Copy the current selection to the clipboard and return its text.",
    {},
    category="input",
)
def copy_selection() -> ToolResult:
    pg = _pyautogui()
    if pg is None:
        return ToolResult.fail("Clipboard access isn't available.")
    try:
        pg.hotkey("ctrl", "c")
        time.sleep(0.15)
        text = _clipboard_text()
    except Exception as e:
        return ToolResult.fail(f"I couldn't copy the selection: {e}")
    if not text:
        return ToolResult(False, "Nothing was copied - there may be no selection.", {})
    return ToolResult.success(f"Copied {len(text)} characters.", text=text[:2000])


def _clipboard_text() -> str:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app:
            return QApplication.clipboard().text()
    except Exception:
        pass
    return ""


@registry.tool(
    "wait",
    "Pause for a number of seconds before the next step.",
    {"seconds": {"type": "number", "description": "How long to wait (max 300)", "required": True}},
    category="general",
)
async def wait(seconds: float) -> ToolResult:
    import asyncio

    delay = max(0.0, min(300.0, float(seconds)))
    await asyncio.sleep(delay)
    return ToolResult.success(f"Waited {delay:.0f} seconds.")
