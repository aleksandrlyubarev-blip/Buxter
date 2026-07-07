"""Playwright-backed browser session for the Buxter web layer.

Playwright is an optional dependency (``pip install buxter[web]``), so the
import happens lazily inside :class:`PlaywrightSession` — the rest of the
package keeps working without it.

The session exposes a small, deterministic surface (goto / read_page / click /
fill / upload / screenshot) that the Web Operator Agent drives via tool use.
Interactive elements are addressed by integer ids stamped into the DOM as
``data-buxter-id`` attributes on every ``read_page`` call; ids are only valid
until the next navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_MAX_TEXT_CHARS = 6000

# Stamps data-buxter-id on interactive elements and returns their digest.
# Previously stamped ids are cleared first: after a DOM mutation without
# navigation, a hidden element would otherwise keep its old id while a new
# element gets the same number, and click() would target the stale node.
# Hidden file inputs are kept: they are routinely display:none behind styled
# upload buttons, and set_input_files works on them regardless.
_ANNOTATE_JS = """
() => {
  for (const el of document.querySelectorAll('[data-buxter-id]')) {
    el.removeAttribute('data-buxter-id');
  }
  const selector = 'a, button, input, select, textarea, [role="button"], [onclick]';
  const visible = (el) => {
    if (el.tagName === 'INPUT' && el.type === 'file') return true;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  let n = 0;
  const out = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    n += 1;
    el.setAttribute('data-buxter-id', String(n));
    out.push({
      id: n,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      text: (el.innerText || el.value || '').trim().slice(0, 80),
      name: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      href: (el.getAttribute('href') || '').slice(0, 120),
    });
  }
  return out;
}
"""


@dataclass
class PageDigest:
    """What the agent 'sees': URL, title, visible text and interactive elements."""

    url: str
    title: str
    text: str
    elements: list[dict[str, Any]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"url: {self.url}",
            f"title: {self.title}",
            "",
            "## Visible text (truncated)",
            self.text,
            "",
            "## Interactive elements (id → element)",
        ]
        for el in self.elements:
            attrs = " ".join(
                f"{key}={el[key]!r}"
                for key in ("type", "name", "placeholder", "href")
                if el.get(key)
            )
            label = el.get("text") or ""
            lines.append(f"[{el['id']}] <{el['tag']} {attrs}> {label}".rstrip())
        if not self.elements:
            lines.append("(none found)")
        return "\n".join(lines)


class BrowserSession(Protocol):
    """Surface the Web Operator Agent drives. Fakeable in tests."""

    def goto(self, url: str) -> str: ...
    def read_page(self) -> PageDigest: ...
    def click(self, element_id: int) -> str: ...
    def fill(self, element_id: int, value: str, press_enter: bool = False) -> str: ...
    def select_option(self, element_id: int, value: str) -> str: ...
    def upload_file(self, element_id: int, path: Path) -> str: ...
    def screenshot(self) -> bytes: ...
    def wait(self, seconds: float) -> str: ...
    def close(self) -> None: ...


class PlaywrightSession:
    """Real Chromium session behind the :class:`BrowserSession` protocol."""

    def __init__(
        self,
        headless: bool = True,
        step_timeout_ms: int = 15_000,
        chromium_path: str | None = None,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "playwright is not installed. Run: pip install 'buxter[web]' "
                "&& playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless, executable_path=chromium_path or None
        )
        self._page = self._browser.new_page()
        self._page.set_default_timeout(step_timeout_ms)

    @staticmethod
    def _selector(element_id: int) -> str:
        return f'[data-buxter-id="{int(element_id)}"]'

    def goto(self, url: str) -> str:
        self._page.goto(url, wait_until="domcontentloaded")
        return f"navigated to {self._page.url}"

    def read_page(self) -> PageDigest:
        elements = self._page.evaluate(_ANNOTATE_JS)
        text = self._page.evaluate("() => document.body ? document.body.innerText : ''")
        if len(text) > _MAX_TEXT_CHARS:
            text = text[:_MAX_TEXT_CHARS] + "\n…[truncated]"
        return PageDigest(
            url=self._page.url,
            title=self._page.title(),
            text=text,
            elements=elements,
        )

    def click(self, element_id: int) -> str:
        self._page.click(self._selector(element_id))
        return f"clicked element {element_id}; now at {self._page.url}"

    def fill(self, element_id: int, value: str, press_enter: bool = False) -> str:
        self._page.fill(self._selector(element_id), value)
        if press_enter:
            self._page.keyboard.press("Enter")
        return f"filled element {element_id}"

    def select_option(self, element_id: int, value: str) -> str:
        self._page.select_option(self._selector(element_id), value)
        return f"selected {value!r} in element {element_id}"

    def upload_file(self, element_id: int, path: Path) -> str:
        self._page.set_input_files(self._selector(element_id), str(path))
        return f"uploaded {path.name} into element {element_id}"

    def screenshot(self) -> bytes:
        return self._page.screenshot(type="png")

    def wait(self, seconds: float) -> str:
        seconds = max(0.0, min(float(seconds), 15.0))
        self._page.wait_for_timeout(seconds * 1000)
        return f"waited {seconds:.1f}s"

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


__all__ = ["BrowserSession", "PageDigest", "PlaywrightSession"]
