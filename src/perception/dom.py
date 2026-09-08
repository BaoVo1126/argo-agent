"""
Turn a live page into a short list of things the model can act on.

The model never sees HTML. It sees lines like

    [4] button "Add to cart"  (#add-to-cart-sauce-labs-backpack)

which is enough to choose an action and short enough that a page of sixty
controls still leaves room for the goal and the history.

Two decisions worth stating:

**Ids are per-snapshot, not per-element.** They are indices into the list the
model was just shown, so `click(4)` means "the fourth thing in the list you
were given". Re-perceiving after every action is what keeps that honest: a
stale id from a previous page cannot silently resolve to something else,
because the map is rebuilt.

**Each element carries a selector, resolved at snapshot time.** Acting through
a stored selector rather than an element handle survives the small re-renders
these single-page apps do constantly, and it makes a failure legible: the
error names the selector that stopped matching.
"""

from __future__ import annotations

from dataclasses import dataclass

# One JS pass collects everything: a round trip per element is the difference
# between a 40 ms snapshot and a 4 s one on a page with sixty controls.
_COLLECT = """
() => {
  const out = [];
  const sel = 'a, button, input, select, textarea, [role=button], [role=link], [onclick]';
  const nodes = document.querySelectorAll(sel);

  const cssPath = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const dt = el.getAttribute('data-test');
    if (dt) return `[data-test="${dt}"]`;
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 5; n = n.parentElement) {
      let part = n.tagName.toLowerCase();
      if (n.id) { parts.unshift('#' + CSS.escape(n.id)); break; }
      const siblings = n.parentElement
        ? Array.from(n.parentElement.children).filter(c => c.tagName === n.tagName)
        : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(n) + 1})`;
      parts.unshift(part);
    }
    return parts.join(' > ');
  };

  const role = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'submit' || t === 'button' || t === 'reset') return 'button';
      if (t === 'checkbox' || t === 'radio') return t;
      return 'textbox';
    }
    return tag;
  };

  const label = (el) => {
    // data-test sits after the visible sources but before id, because test
    // hooks are usually written to describe the control ("error-button")
    // while ids on these apps often repeat the field name.
    //
    // It earns its place: saucedemo's dismiss-error control has no text, no
    // aria-label and no value, so it reached the model as an unlabelled
    // `button (...)`. Faced with a nameless button, the agent clicked it --
    // which removes the error message from the DOM, and with it the evidence
    // the task was about.
    const own =
      el.getAttribute('aria-label') ||
      (el.innerText || '').trim() ||
      el.getAttribute('placeholder') ||
      el.getAttribute('name') ||
      el.getAttribute('value') ||
      el.getAttribute('data-test') ||
      el.getAttribute('title') ||
      el.id || '';
    return own.replace(/\\s+/g, ' ').trim().slice(0, 80);
  };

  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    // Zero-area or hidden controls are not actionable, and listing them
    // invites the model to pick one and stall.
    if (r.width === 0 || r.height === 0) continue;
    if (style.visibility === 'hidden' || style.display === 'none') continue;

    out.push({
      role: role(el),
      text: label(el),
      selector: cssPath(el),
      value: el.value === undefined ? null : String(el.value).slice(0, 60),
      enabled: !el.disabled,
      options: el.tagName.toLowerCase() === 'select'
        ? Array.from(el.options).map(o => o.value).slice(0, 20)
        : null,
    });
  }
  return out;
}
"""


@dataclass
class Element:
    id: int
    role: str
    text: str
    selector: str
    value: str | None = None
    enabled: bool = True
    options: list[str] | None = None

    def render(self) -> str:
        parts = [f"[{self.id}] {self.role}"]
        if self.text:
            parts.append(f'"{self.text}"')
        if self.value:
            parts.append(f"value={self.value!r}")
        if self.options:
            parts.append(f"options={self.options}")
        if not self.enabled:
            parts.append("(disabled)")
        parts.append(f"({self.selector})")
        return " ".join(parts)


@dataclass
class Snapshot:
    url: str
    title: str
    elements: list[Element]
    # Page text is the only way the model can tell "logged in" from "error
    # message shown" -- both pages expose the same controls.
    text: str

    def render(self, max_elements: int) -> str:
        shown = self.elements[:max_elements]
        lines = [f"URL: {self.url}", f"TITLE: {self.title}", ""]
        if self.text:
            lines += ["PAGE TEXT (truncated):", self.text, ""]
        lines.append(f"ELEMENTS ({len(shown)} of {len(self.elements)}):")
        lines += [e.render() for e in shown]
        return "\n".join(lines)

    def by_id(self, element_id: int) -> Element | None:
        for element in self.elements:
            if element.id == element_id:
                return element
        return None


def perceive(page, max_text_chars: int = 800) -> Snapshot:
    raw = page.evaluate(_COLLECT)
    elements = [
        Element(
            id=index,
            role=item["role"],
            text=item["text"],
            selector=item["selector"],
            value=item["value"] or None,
            enabled=bool(item["enabled"]),
            options=item["options"] or None,
        )
        for index, item in enumerate(raw, start=1)
    ]
    body = page.inner_text("body") if page.query_selector("body") else ""
    text = " ".join(body.split())[:max_text_chars]
    return Snapshot(url=page.url, title=page.title(), elements=elements, text=text)
