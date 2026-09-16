"""Browser automation via Playwright.

One reusable browser instance is kept alive between commands so "open this page"
then "click the download link" work as a conversation. Everything degrades with
a clear message when Playwright isn't installed.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..paths import downloads_dir
from .registry import ToolResult, registry

log = get_logger("tools.browser")

INSTALL_HINT = ("Browser automation needs Playwright. Install it with: "
                "pip install playwright  then  playwright install chromium")


class BrowserSession:
    """Holds the live Playwright objects. Created lazily, closed on shutdown."""

    def __init__(self) -> None:
        self._pw: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self.settings: Any = None
        self._lock = asyncio.Lock()
        self.last_content_hash = ""

    def configure(self, settings: Any) -> None:
        self.settings = settings

    def _opt(self, key: str, default: Any) -> Any:
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    @property
    def active(self) -> bool:
        return self.page is not None

    async def ensure(self) -> tuple[bool, str]:
        async with self._lock:
            if self.page is not None:
                try:
                    await self.page.title()  # cheap liveness probe
                    return True, ""
                except Exception:
                    log.info("Browser session died; restarting it.")
                    await self._reset()
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return False, INSTALL_HINT
            try:
                self._pw = await async_playwright().start()
                channel = str(self._opt("browser_channel", "chrome"))
                headless = bool(self._opt("browser_headless", False))
                launch: dict[str, Any] = {"headless": headless}
                if channel in {"chrome", "msedge"}:
                    launch["channel"] = channel
                try:
                    self.browser = await self._pw.chromium.launch(**launch)
                except Exception:
                    # Requested channel not installed -> bundled chromium
                    self.browser = await self._pw.chromium.launch(headless=headless)
                dl = self._opt("browser_download_dir", "") or str(downloads_dir())
                self.context = await self.browser.new_context(
                    accept_downloads=True,
                    viewport={"width": 1440, "height": 900},
                )
                self.context.set_default_timeout(20000)
                self.page = await self.context.new_page()
                self._download_dir = Path(dl)
                return True, ""
            except Exception as e:
                await self._reset()
                return False, f"I couldn't start the browser: {e}"

    async def _reset(self) -> None:
        for obj in (self.context, self.browser):
            try:
                if obj:
                    await obj.close()
            except Exception:
                pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._pw = self.browser = self.context = self.page = None

    async def close(self) -> None:
        async with self._lock:
            await self._reset()


session = BrowserSession()


async def _page() -> tuple[Any, str]:
    ok, err = await session.ensure()
    if not ok:
        return None, err
    return session.page, ""


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url):
        if " " in url or "." not in url:
            return ""
        url = "https://" + url
    return url


@registry.tool(
    "browser_open",
    "Open a web page in the automated browser.",
    {"url": {"type": "string", "description": "Web address to open", "required": True}},
    category="browser",
)
async def browser_open(url: str) -> ToolResult:
    target = _normalize_url(url)
    if not target:
        return ToolResult.fail(f"'{url}' doesn't look like a web address.")
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    try:
        response = await page.goto(target, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return ToolResult.fail(f"The page didn't load: {_short_err(e)}")
    status = response.status if response else 0
    if status >= 400:
        return ToolResult.fail(f"{target} returned HTTP {status}.", url=target, status=status)
    title = await page.title()
    return ToolResult.success(f"Opened {title or target}.", url=page.url, title=title, status=status)


@registry.tool(
    "browser_search",
    "Search the web and return the top results.",
    {"query": {"type": "string", "description": "What to search for", "required": True},
     "engine": {"type": "string", "description": "Search engine", "enum": ["duckduckgo", "google", "bing"],
                "default": "duckduckgo"}},
    category="browser",
)
async def browser_search(query: str, engine: str = "duckduckgo") -> ToolResult:
    urls = {
        "duckduckgo": "https://duckduckgo.com/?q=",
        "google": "https://www.google.com/search?q=",
        "bing": "https://www.bing.com/search?q=",
    }
    from urllib.parse import quote_plus

    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    target = urls.get(engine, urls["duckduckgo"]) + quote_plus(query)
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)
        results = await page.evaluate(
            """() => {
                const out = [];
                const sels = ['a[data-testid="result-title-a"]', 'div#search a h3', 'li.b_algo h2 a', 'h3'];
                for (const sel of sels) {
                    document.querySelectorAll(sel).forEach(el => {
                        const a = el.tagName === 'A' ? el : el.closest('a');
                        const title = (el.innerText || '').trim();
                        if (a && title && out.length < 8) out.push({title, url: a.href});
                    });
                    if (out.length) break;
                }
                return out;
            }"""
        )
    except Exception as e:
        return ToolResult.fail(f"The search didn't complete: {_short_err(e)}")
    if not results:
        return ToolResult(False, f"I searched for '{query}' but couldn't read any results.",
                          {"url": page.url})
    top = results[0]["title"]
    return ToolResult.success(f"I found {len(results)} results. The top one is: {top}.",
                              results=results, url=page.url)


@registry.tool(
    "browser_read",
    "Read the visible text of the current web page, or answer what it contains.",
    {"max_chars": {"type": "integer", "description": "How much text to return", "default": 3000}},
    category="browser",
)
async def browser_read(max_chars: int = 3000) -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    if not page.url or page.url == "about:blank":
        return ToolResult.fail("No page is open yet.")
    try:
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        title = await page.title()
    except Exception as e:
        return ToolResult.fail(f"I couldn't read the page: {_short_err(e)}")
    clean = re.sub(r"\n{3,}", "\n\n", (text or "").strip())[:max(500, max_chars)]
    return ToolResult.success(f"Read {len(clean)} characters from {title}.",
                              title=title, url=page.url, text=clean)


@registry.tool(
    "browser_click",
    "Click a link or button on the current page by its visible text.",
    {"text": {"type": "string", "description": "Visible text of the element", "required": True},
     "index": {"type": "integer", "description": "Which match to click if several", "default": 0}},
    category="browser",
)
async def browser_click(text: str, index: int = 0) -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    try:
        locator = page.get_by_text(text, exact=False)
        count = await locator.count()
        if count == 0:
            locator = page.locator(f"a:has-text('{text}'), button:has-text('{text}')")
            count = await locator.count()
        if count == 0:
            return ToolResult.fail(f"I couldn't find '{text}' on this page.")
        if count > 1 and index == 0:
            log.info("%d matches for '%s'; clicking the first.", count, text)
        await locator.nth(min(index, count - 1)).click(timeout=10000)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception as e:
        return ToolResult.fail(f"I couldn't click '{text}': {_short_err(e)}")
    return ToolResult.success(f"Clicked '{text}'.", url=page.url, matches=count)


@registry.tool(
    "browser_type",
    "Type into an input field on the current page.",
    {"text": {"type": "string", "description": "Text to enter", "required": True},
     "field": {"type": "string", "description": "Label, placeholder or name of the field"},
     "press_enter": {"type": "boolean", "description": "Submit with Enter", "default": False}},
    category="browser",
)
async def browser_type(text: str, field: str = "", press_enter: bool = False) -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    try:
        if field:
            locator = page.get_by_placeholder(field)
            if await locator.count() == 0:
                locator = page.get_by_label(field)
            if await locator.count() == 0:
                locator = page.locator(f"input[name='{field}'], textarea[name='{field}'], #{field}")
            if await locator.count() == 0:
                return ToolResult.fail(f"I couldn't find a field called '{field}'.")
            element = locator.first
        else:
            element = page.locator("input[type='text'], input[type='search'], textarea").first
            if await element.count() == 0:
                return ToolResult.fail("I couldn't find a text field on this page.")
        await element.fill(text, timeout=10000)
        if press_enter:
            await element.press("Enter")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception as e:
        return ToolResult.fail(f"I couldn't type into the page: {_short_err(e)}")
    return ToolResult.success(f"Entered text into {field or 'the field'}.", url=page.url)


@registry.tool(
    "browser_scroll",
    "Scroll the current web page.",
    {"direction": {"type": "string", "enum": ["up", "down", "bottom", "top"], "default": "down"}},
    category="browser",
)
async def browser_scroll(direction: str = "down") -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    js = {
        "down": "window.scrollBy(0, window.innerHeight * 0.85)",
        "up": "window.scrollBy(0, -window.innerHeight * 0.85)",
        "bottom": "window.scrollTo(0, document.body.scrollHeight)",
        "top": "window.scrollTo(0, 0)",
    }.get(direction, "window.scrollBy(0, 600)")
    try:
        await page.evaluate(f"() => {{ {js} }}")
    except Exception as e:
        return ToolResult.fail(f"I couldn't scroll the page: {_short_err(e)}")
    return ToolResult.success(f"Scrolled {direction}.")


@registry.tool(
    "browser_wait",
    "Wait for an element or text to appear on the page.",
    {"text": {"type": "string", "description": "Text or CSS selector to wait for", "required": True},
     "timeout_s": {"type": "integer", "description": "Seconds to wait", "default": 20}},
    category="browser",
)
async def browser_wait(text: str, timeout_s: int = 20) -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    ms = max(1000, min(120000, timeout_s * 1000))
    try:
        if text.startswith((".", "#", "[")) or "div" in text[:4]:
            await page.wait_for_selector(text, timeout=ms)
        else:
            await page.get_by_text(text, exact=False).first.wait_for(timeout=ms)
    except Exception:
        return ToolResult.fail(f"'{text}' didn't appear within {timeout_s} seconds.")
    return ToolResult.success(f"'{text}' appeared on the page.")


@registry.tool(
    "browser_download",
    "Download a file from the current page by clicking a link.",
    {"link_text": {"type": "string", "description": "Visible text of the download link", "required": True},
     "save_folder": {"type": "string", "description": "Where to save it", "default": ""}},
    category="browser",
)
async def browser_download(link_text: str, save_folder: str = "") -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    from .files import resolve_path

    dest_dir = resolve_path(save_folder) if save_folder else downloads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with page.expect_download(timeout=60000) as info:
            await page.get_by_text(link_text, exact=False).first.click(timeout=10000)
        download = await info.value
        target = dest_dir / (download.suggested_filename or "download")
        await download.save_as(str(target))
    except Exception as e:
        return ToolResult.fail(f"The download didn't complete: {_short_err(e)}")
    if not target.exists():
        return ToolResult.fail("The download finished but I couldn't find the file.")
    size_kb = round(target.stat().st_size / 1024, 1)
    return ToolResult.success(f"Downloaded {target.name} ({size_kb} KB) to {dest_dir.name}.",
                              path=str(target), size_kb=size_kb)


@registry.tool(
    "browser_download_all",
    "Download every file of a given type linked on the current page, into a folder.",
    {"extension": {"type": "string", "description": "File type such as pdf", "default": "pdf"},
     "save_folder": {"type": "string", "description": "Destination folder", "required": True},
     "limit": {"type": "integer", "description": "Maximum files", "default": 25}},
    category="browser",
)
async def browser_download_all(save_folder: str, extension: str = "pdf", limit: int = 25) -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    from .files import resolve_path

    ext = extension.lower().lstrip(".")
    dest = resolve_path(save_folder)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        links = await page.evaluate(
            """(ext) => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => h.toLowerCase().includes('.' + ext))""",
            ext,
        )
    except Exception as e:
        return ToolResult.fail(f"I couldn't read the links on this page: {_short_err(e)}")
    links = list(dict.fromkeys(links))[:limit]
    if not links:
        return ToolResult(False, f"I didn't find any .{ext} links on this page.", {"count": 0})

    saved, failed = [], []
    for url in links:
        try:
            resp = await session.context.request.get(url, timeout=60000)
            if resp.status >= 400:
                failed.append(url)
                continue
            name = url.split("/")[-1].split("?")[0] or f"file.{ext}"
            path = dest / name
            path.write_bytes(await resp.body())
            saved.append(str(path))
        except Exception:
            failed.append(url)
    if not saved:
        return ToolResult.fail(f"I found {len(links)} links but none downloaded successfully.")
    msg = f"Downloaded {len(saved)} {ext.upper()} files to {dest.name}."
    if failed:
        msg += f" {len(failed)} failed."
    return ToolResult.success(msg, saved=saved, failed=len(failed), folder=str(dest))


@registry.tool(
    "browser_upload",
    "Upload a local file into a file input on the current page.",
    {"file_path": {"type": "string", "description": "Full path of the file to upload", "required": True},
     "field": {"type": "string", "description": "Optional file input selector"}},
    category="browser",
)
async def browser_upload(file_path: str, field: str = "") -> ToolResult:
    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    from .files import resolve_path

    src = resolve_path(file_path)
    if not src.exists():
        return ToolResult.fail(f"I couldn't find {src}.")
    try:
        locator = page.locator(field) if field else page.locator("input[type='file']").first
        await locator.set_input_files(str(src), timeout=15000)
    except Exception as e:
        return ToolResult.fail(f"I couldn't attach the file: {_short_err(e)}")
    return ToolResult.success(f"Attached {src.name} to the page.", path=str(src))


@registry.tool(
    "browser_screenshot",
    "Take a screenshot of the current web page.",
    {"full_page": {"type": "boolean", "description": "Capture the whole page", "default": False}},
    category="browser",
)
async def browser_screenshot(full_page: bool = False) -> ToolResult:
    import time as _t

    from ..paths import screenshots_dir

    page, err = await _page()
    if page is None:
        return ToolResult.fail(err)
    path = screenshots_dir() / f"page_{int(_t.time())}.png"
    try:
        await page.screenshot(path=str(path), full_page=full_page)
    except Exception as e:
        return ToolResult.fail(f"I couldn't capture the page: {_short_err(e)}")
    return ToolResult.success("Captured the web page.", path=str(path))


@registry.tool(
    "browser_close",
    "Close the automated browser.",
    {},
    category="browser",
)
async def browser_close() -> ToolResult:
    if not session.active:
        return ToolResult.success("The browser isn't open.")
    await session.close()
    return ToolResult.success("Closed the browser.")


def _short_err(e: Exception) -> str:
    msg = str(e).split("\n")[0]
    return msg[:160]
