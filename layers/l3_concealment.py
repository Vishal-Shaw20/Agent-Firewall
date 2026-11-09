"""
l3_concealment.py — Concealment layer (L3) for Agent Firewall.

Two signals, fused (SRS FR5 + FR6):
  1. Rule-based: inline / <style> CSS and attributes that hide text from a
     human reader (display:none, opacity:0, off-screen, tiny font, colour
     equal to background, ...), HTML comments, zero-width and Unicode tag
     characters.
  2. Render-diff: the page is rendered offline in headless Chromium and the
     text a human would see is diffed against the DOM text. Visible text comes
     from Tesseract OCR on a screenshot when Tesseract is installed, otherwise
     from a computed-style visibility pass in the browser. This catches hiding
     techniques the rule list does not know about.

Hidden text is then checked with L1, so hidden instructions score higher
than hidden prose.
"""

import os
import re
import shutil
import threading
import queue
from collections import Counter
from concurrent.futures import Future, TimeoutError as FutureTimeout

from bs4 import BeautifulSoup, Comment

from layers.l1_heuristic import run_l1_heuristic
from settings import firewall_config

_cfg            = firewall_config().get("l3", {})
RENDER_ENABLED  = _cfg.get("render_enabled", True)
RENDER_BUDGET_S = _cfg.get("render_budget_s", 1.5)
MIN_HIDDEN_WORDS = _cfg.get("min_hidden_words", 8)

SCORE_HIDDEN_INSTRUCTION = 0.90   # hidden text that L1 flags
SCORE_HIDDEN_TEXT        = 0.60   # a block of hidden prose
SCORE_TAG_CHARS          = 0.70   # Unicode tag-character smuggling
SCORE_ZERO_WIDTH         = 0.30

HTML_RE       = re.compile(r"<\s*(html|body|div|span|p|section|article|style|!--)[\s>]", re.I)
ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
TAG_CHARS_RE  = re.compile("[\U000E0020-\U000E007E]+")
SKIP_TAGS     = {"script", "style", "head", "title", "meta", "link"}

HIDING_DECLS = [
    re.compile(r"display\s*:\s*none"),
    re.compile(r"visibility\s*:\s*hidden"),
    re.compile(r"opacity\s*:\s*0(\.0\d*)?\s*(;|$|!)"),
    re.compile(r"font-size\s*:\s*(0|0?\.\d+|1)(px|pt|em|rem)?\s*(;|$|!)"),
    re.compile(r"(left|top|text-indent|margin-left)\s*:\s*-\d{3,}"),
    re.compile(r"(height|width|max-height)\s*:\s*0(px)?\s*;.*overflow\s*:\s*hidden"),
    re.compile(r"clip\s*:\s*rect\(\s*0"),
    re.compile(r"color\s*:\s*transparent"),
]
COLOR_RE = re.compile(r"(?<![-\w])color\s*:\s*([^;]+)")
BG_RE    = re.compile(r"background(-color)?\s*:\s*([^;]+)")


def is_html(content: str) -> bool:
    return bool(HTML_RE.search(content))


def _norm_color(c: str) -> str:
    c = c.strip().lower().replace(" ", "")
    aliases = {"white": "#fff", "#ffffff": "#fff", "black": "#000", "#000000": "#000"}
    return aliases.get(c, c)


def _style_hides(style: str) -> bool:
    style = style.lower()
    if any(p.search(style) for p in HIDING_DECLS):
        return True
    fg, bg = COLOR_RE.search(style), BG_RE.search(style)
    return bool(fg and bg and _norm_color(fg.group(1)) == _norm_color(bg.group(2)))


def _hidden_selectors(soup: BeautifulSoup) -> tuple[set, set]:
    """Classes / ids that <style> blocks hide."""
    classes, ids = set(), set()
    for style in soup.find_all("style"):
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", style.get_text()):
            if _style_hides(body):
                classes |= set(re.findall(r"\.([\w-]+)", selector))
                ids     |= set(re.findall(r"#([\w-]+)", selector))
    return classes, ids


def _element_hidden(el, classes: set, ids: set) -> bool:
    for node in [el, *el.parents]:
        if getattr(node, "name", None) is None:
            continue
        if node.has_attr("hidden"):
            return True
        if node.has_attr("style") and _style_hides(node["style"]):
            return True
        if classes & set(node.get("class", [])):
            return True
        if node.get("id") in ids:
            return True
    return False


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _visible_dom_text(soup: BeautifulSoup) -> str:
    parts = []
    for node in soup.find_all(string=True):
        if isinstance(node, Comment) or node.parent.name in SKIP_TAGS:
            continue
        parts.append(str(node))
    return " ".join(parts)


# ── Rule-based pass ───────────────────────────────────────
def rule_scan(content: str) -> list[dict]:
    """Returns hidden text blocks: {technique, text}."""
    blocks = []

    # Unicode tag characters: invisible ASCII smuggling, decoded here
    for m in TAG_CHARS_RE.finditer(content):
        decoded = "".join(chr(ord(ch) - 0xE0000) for ch in m.group(0))
        blocks.append({"technique": "unicode_tag_chars", "text": decoded, "raw": m.group(0)})

    zero_width = len(ZERO_WIDTH_RE.findall(content))
    if zero_width >= 3:
        blocks.append({"technique": "zero_width_chars", "text": "", "count": zero_width})

    if not is_html(content):
        return blocks

    soup = BeautifulSoup(content, "html.parser")
    classes, ids = _hidden_selectors(soup)

    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if len(_words(comment)) >= MIN_HIDDEN_WORDS:
            blocks.append({"technique": "html_comment", "text": comment.strip()})

    seen = set()
    for node in soup.find_all(string=True):
        if isinstance(node, Comment) or node.parent.name in SKIP_TAGS or not node.strip():
            continue
        if _element_hidden(node.parent, classes, ids):
            # Group by the outermost hidden ancestor so a hidden div is one block
            owner = node.parent
            for anc in node.parent.parents:
                if getattr(anc, "name", None) and _element_hidden(anc, classes, ids):
                    owner = anc
            if id(owner) in seen:
                continue
            seen.add(id(owner))
            text = owner.get_text(" ", strip=True)
            blocks.append({"technique": "css_or_attribute", "text": text})

    return blocks


# ── Render-diff worker (one browser, one thread) ──────────
_VISIBLE_JS = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  const W = document.documentElement.scrollWidth, H = document.documentElement.scrollHeight;
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor;
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c;
    }
    return 'rgb(255, 255, 255)';
  };
  while (walker.nextNode()) {
    const node = walker.currentNode, el = node.parentElement;
    if (!el || !node.textContent.trim()) continue;
    if (['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'].includes(el.tagName)) continue;
    // Collapsed <details> content is one click away for the reader: not concealed
    if (el.closest('details')) { out.push(node.textContent); continue; }
    if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
    const s = getComputedStyle(el);
    if (parseFloat(s.fontSize) < 4) continue;
    if (s.color === bgOf(el) || s.color === 'rgba(0, 0, 0, 0)') continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.right + window.scrollX <= 0 || r.bottom + window.scrollY <= 0 || r.left >= W || r.top >= H) continue;
    let clipped = false;
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e), b = e.getBoundingClientRect();
      if ((cs.overflow === 'hidden' || cs.clip !== 'auto') && (b.width < 2 || b.height < 2)) { clipped = true; break; }
    }
    if (!clipped) out.push(node.textContent);
  }
  return out.join(' ');
}
"""


def _tesseract_path() -> str | None:
    found = shutil.which("tesseract")
    default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return found or (default if os.path.exists(default) else None)


class _RenderWorker:
    """Owns a headless Chromium on a dedicated thread (Playwright objects are thread-bound)."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, html: str) -> Future:
        fut: Future = Future()
        self._jobs.put((html, fut))
        return fut

    def _run(self):
        from playwright.sync_api import sync_playwright
        tesseract = _tesseract_path()
        if tesseract:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1280, "height": 1600},
                                          java_script_enabled=True, offline=True)
            while True:
                html, fut = self._jobs.get()
                if fut.cancelled():
                    continue
                try:
                    page = context.new_page()
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(html, wait_until="domcontentloaded", timeout=5000)
                    if tesseract:
                        import io
                        from PIL import Image
                        shot    = page.screenshot(full_page=True)
                        visible = pytesseract.image_to_string(Image.open(io.BytesIO(shot)))
                        method  = "ocr"
                    else:
                        visible = page.evaluate(_VISIBLE_JS)
                        method  = "computed_style"
                    page.close()
                    fut.set_result((visible, method))
                except Exception as e:  # noqa: BLE001 — report, never crash the worker
                    fut.set_exception(e)


_worker = None
_worker_lock = threading.Lock()


def _get_worker() -> _RenderWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _RenderWorker()
        return _worker


def render_diff(content: str, budget_s: float = RENDER_BUDGET_S) -> dict:
    """
    Returns {"status": ok|pending|error|skipped, "hidden_text", "method", ...}.
    Hidden text = DOM words that do not appear in the rendered visible text.
    """
    if not RENDER_ENABLED or not is_html(content):
        return {"status": "skipped"}
    fut = _get_worker().submit(content)
    try:
        visible, method = fut.result(timeout=budget_s)
    except FutureTimeout:
        return {"status": "pending"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    soup          = BeautifulSoup(content, "html.parser")
    dom_words     = _words(_visible_dom_text(soup))
    # Collapsed <details> content is one click away for the reader, so it isn't
    # concealed. The JS pass already counts it as visible; OCR can't see it.
    if method == "ocr":
        visible += " " + " ".join(d.get_text(" ") for d in soup.find_all("details"))
    visible_count = Counter(_words(visible))
    hidden = []
    for w in dom_words:
        if visible_count[w] > 0:
            visible_count[w] -= 1
        else:
            hidden.append(w)
    return {
        "status": "ok",
        "method": method,
        "dom_words": len(dom_words),
        "hidden_words": len(hidden),
        "hidden_text": " ".join(hidden),
    }


def warm_up():
    """Start the browser before the first request (called at proxy startup)."""
    if RENDER_ENABLED:
        render_diff("<html><body><p>warm up</p></body></html>", budget_s=30)


# ── Entry point ───────────────────────────────────────────
def _score_text(text: str) -> tuple[float, list[str]]:
    l1 = run_l1_heuristic(text)
    if l1["score"] > 0:
        return SCORE_HIDDEN_INSTRUCTION, l1["matched"]
    if len(_words(text)) >= MIN_HIDDEN_WORDS:
        return SCORE_HIDDEN_TEXT, []
    return 0.0, []


def run_l3_concealment(content: str, render: bool = True) -> dict:
    blocks = rule_scan(content)
    score, spans, matched = 0.0, [], []

    for b in blocks:
        if b["technique"] == "zero_width_chars":
            s = SCORE_ZERO_WIDTH
        elif b["technique"] == "unicode_tag_chars":
            s, m = _score_text(b["text"])
            s = max(s, SCORE_TAG_CHARS)
            matched += m
        else:
            s, m = _score_text(b["text"])
            matched += m
        b["score"] = s
        score = max(score, s)
        if s >= 0.5:
            spans.append(b.get("raw", b["text"]))

    rd = render_diff(content) if render else {"status": "skipped"}
    if rd["status"] == "ok" and rd["hidden_words"]:
        s, m = _score_text(rd["hidden_text"])
        rd["score"] = s
        score = max(score, s)
        matched += m

    return {
        "score": score,
        "layer": "L3_concealment",
        "blocks": [{k: v for k, v in b.items() if k != "raw"} for b in blocks],
        "render_diff": rd,
        "render_pending": rd["status"] == "pending",
        "matched": matched,
        "spans": spans,
    }
