"""Mock page.css mini-DOM cho test crawler: meta, title, .class/#id, img, wrapper chứa img."""
from __future__ import annotations

import re
from unittest.mock import MagicMock


def _attrs_from(raw: str) -> dict:
    attrs: dict = {}
    for kv in raw.split():
        if "=" not in kv:
            continue
        key, _, val = kv.partition("=")
        attrs[key.strip()] = val.strip("\"'")
    return attrs


def _mock_meta_dom_page(html: str = "", meta: dict | None = None) -> MagicMock:
    """Page giả lập Scrapling Adaptor với mini-DOM.

    - meta: {"og:title": "...", ...} → khớp meta[property=...] / meta[name=...]
    - html: DOM giả dạng chuỗi. Hỗ trợ:
      * ``<meta property="og:x" content="y">`` / ``<meta name="x" content="y">``
      * ``<title>text</title>``
      * ``<img ...>`` với attrs src/data-src/data-original/data-lazy-src/srcset
      * wrapper ``<div|span|p|h1|h2|h3|em|strong class="c" id="i">text</...>``
        chứa text hoặc ``<img>`` con.
    Selector hỗ trợ: ``meta[...]``, ``title``, ``img``, ``source``, ``.class``,
    ``#id``, ``tag``, và kết hợp ``tag.class``. Không hỗ trợ tổ hợp phức tạp.
    """
    page = MagicMock()
    meta = meta or {}

    wrappers: list[tuple[str, dict, str, list]] = []  # (tag, attrs, text, img_children)
    imgs: list = []

    for m in re.finditer(r"<img\s([^>]*?)/?>", html):
        attrs = _attrs_from(m.group(1))
        node = MagicMock()
        node.tag = "img"
        node.attrib = attrs
        node.css = MagicMock(return_value=[])
        imgs.append(node)

    # wrapper kèm <img> con: <div class="x" ...><img ...></div>
    for m in re.finditer(r"<(div|span|p|h1|h2|h3|a)\b([^>]*)>(.*?)</\1>", html, re.DOTALL):
        inner = m.group(3)
        children: list = []
        if "<img" in inner:
            for im in re.finditer(r"<img\s([^>]*?)/?>", inner):
                attrs = _attrs_from(im.group(1))
                node = MagicMock()
                node.tag = "img"
                node.attrib = attrs
                node.css = MagicMock(return_value=[])
                children.append(node)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text and not children:
            continue
        wrappers.append((m.group(1), _attrs_from(m.group(2)), text, children))

    # <title>
    title_text = ""
    tm = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    if tm:
        title_text = tm.group(1).strip()

    def _make_meta_node(content: str):
        node = MagicMock()
        node.attrib = {"content": content}
        return node

    def _matches(el_tag: str, el_attrs: dict, selector: str) -> bool:
        sel = selector.strip()
        # selector tổng quát: [tag][#id][.class...]
        m = re.fullmatch(r"([a-zA-Z][\w-]*)?(#[\w-]+)?((?:\.[\w-]+)*)", sel)
        if not m or not any(m.groups()):
            return False
        tag = m.group(1)
        eid = (m.group(2) or "").lstrip("#")
        classes = [c for c in (m.group(3) or "").split(".") if c]
        if tag and el_tag != tag:
            return False
        if eid and el_attrs.get("id") != eid:
            return False
        el_classes = (el_attrs.get("class") or "").split()
        return all(c in el_classes for c in classes)

    def _css(selector: str):
        if selector.startswith("meta["):
            for key, val in meta.items():
                if f'"{key}"' in selector:
                    return [_make_meta_node(val)]
            return []
        if selector == "title":
            return []
        if selector in ("img", "source"):
            return list(imgs)
        # selector chứa img/source đứng cuối → con của wrapper (vd ".book-img img")
        parts = selector.split()
        if len(parts) >= 2 and parts[-1] in ("img", "source"):
            parent_sel = " ".join(parts[:-1])
            out: list = []
            for _pos, tag, attrs, _text, children in wrappers:
                if _matches(tag, attrs, parent_sel):
                    out.extend(children)
            return out
        for tag, attrs, text, children in wrappers:
            if _matches(tag, attrs, selector):
                node = MagicMock()
                node.tag = tag
                node.attrib = attrs
                node.text = text
                node.get_all_text = MagicMock(return_value=text)

                def _child_css(sel: str, _children=children):
                    if "img" in sel or "source" in sel:
                        return list(_children)
                    return []

                node.css = _child_css
                return [node]
        for node in imgs:
            if _matches("img", node.attrib, selector):
                return [node]
        return []

    page.css = _css
    return page
