from __future__ import annotations

import base64
import html
import mimetypes
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V_NS = "urn:schemas-microsoft-com:vml"

NS = {"w": W_NS, "r": R_NS, "a": A_NS, "wp": WP_NS, "pic": PIC_NS, "v": V_NS}


def qn(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


def w(name: str) -> str:
    return qn(W_NS, name)


def r(name: str) -> str:
    return qn(R_NS, name)


def twips_to_pt(value: str | None, default: float = 0.0) -> float:
    try:
        return int(value or 0) / 20.0
    except (TypeError, ValueError):
        return default


def twips_to_mm(value: str | None, default: float = 0.0) -> float:
    try:
        return int(value or 0) * 25.4 / 1440.0
    except (TypeError, ValueError):
        return default


def half_points_to_pt(value: str | None, default: float = 11.0) -> float:
    try:
        return int(value or 0) / 2.0
    except (TypeError, ValueError):
        return default


def on_off(element: ET.Element | None) -> bool:
    if element is None:
        return False
    value = element.get(w("val"))
    return value not in {"0", "false", "False", "off", "none"}


def css_escape_font(value: str) -> str:
    value = value.strip().replace('"', "")
    return f'"{value}"' if " " in value else value


@dataclass
class PageSetup:
    width_mm: float = 210.0
    height_mm: float = 297.0
    top_mm: float = 15.0
    right_mm: float = 20.0
    bottom_mm: float = 18.0
    left_mm: float = 20.0
    header_mm: float = 8.0
    footer_mm: float = 8.0
    first_header_target: str | None = None
    default_header_target: str | None = None
    first_footer_target: str | None = None
    default_footer_target: str | None = None
    title_page: bool = False


class DocxPrintRenderer:
    """Render a DOCX into paged HTML suitable for browser Print / Save as PDF.

    The renderer intentionally uses only Python's standard library. It follows the
    Word last-rendered page-break markers when present, so documents last saved by
    Word generally keep their existing pagination. It is not a substitute for the
    Microsoft Word rendering engine, but it preserves the document structure,
    common paragraph/run formatting, tables, headers, footers and embedded images.
    """

    def __init__(self, source: Path, *, filename: str | None = None):
        self.source = Path(source)
        self.filename = filename or self.source.name
        self.archive = zipfile.ZipFile(self.source)
        self.document = self._xml("word/document.xml")
        self.styles = self._load_styles()
        self.numbering = self._load_numbering()
        self.document_rels = self._load_rels("word/_rels/document.xml.rels")
        self.setup = self._page_setup()
        self.list_counters: dict[tuple[str, int], int] = {}

    def close(self) -> None:
        self.archive.close()

    def __enter__(self) -> "DocxPrintRenderer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _xml(self, member: str) -> ET.Element:
        return ET.fromstring(self.archive.read(member))

    def _load_rels(self, member: str) -> dict[str, str]:
        if member not in self.archive.namelist():
            return {}
        root = self._xml(member)
        result: dict[str, str] = {}
        for rel in root:
            rel_id = rel.get("Id")
            target = rel.get("Target")
            if rel_id and target:
                result[rel_id] = target
        return result

    def _load_styles(self) -> dict[str, dict[str, ET.Element | str | None]]:
        if "word/styles.xml" not in self.archive.namelist():
            return {}
        root = self._xml("word/styles.xml")
        styles: dict[str, dict[str, ET.Element | str | None]] = {}
        for style in root.findall("w:style", NS):
            style_id = style.get(w("styleId"))
            if not style_id:
                continue
            based = style.find("w:basedOn", NS)
            styles[style_id] = {
                "based_on": based.get(w("val")) if based is not None else None,
                "pPr": style.find("w:pPr", NS),
                "rPr": style.find("w:rPr", NS),
                "name": (style.find("w:name", NS).get(w("val")) if style.find("w:name", NS) is not None else style_id),
            }
        defaults = root.find("w:docDefaults", NS)
        if defaults is not None:
            p_default = defaults.find("w:pPrDefault/w:pPr", NS)
            r_default = defaults.find("w:rPrDefault/w:rPr", NS)
            styles["__default__"] = {"based_on": None, "pPr": p_default, "rPr": r_default, "name": "Default"}
        return styles

    def _load_numbering(self) -> dict[str, dict[int, tuple[str, str, int]]]:
        if "word/numbering.xml" not in self.archive.namelist():
            return {}
        root = self._xml("word/numbering.xml")
        abstract: dict[str, dict[int, tuple[str, str, int]]] = {}
        for node in root.findall("w:abstractNum", NS):
            abstract_id = node.get(w("abstractNumId"))
            if abstract_id is None:
                continue
            levels: dict[int, tuple[str, str, int]] = {}
            for lvl in node.findall("w:lvl", NS):
                ilvl = int(lvl.get(w("ilvl"), "0"))
                fmt_el = lvl.find("w:numFmt", NS)
                text_el = lvl.find("w:lvlText", NS)
                start_el = lvl.find("w:start", NS)
                levels[ilvl] = (
                    fmt_el.get(w("val"), "decimal") if fmt_el is not None else "decimal",
                    text_el.get(w("val"), f"%{ilvl + 1}.") if text_el is not None else f"%{ilvl + 1}.",
                    int(start_el.get(w("val"), "1")) if start_el is not None else 1,
                )
            abstract[abstract_id] = levels
        num_map: dict[str, dict[int, tuple[str, str, int]]] = {}
        for num in root.findall("w:num", NS):
            num_id = num.get(w("numId"))
            abstract_el = num.find("w:abstractNumId", NS)
            if num_id and abstract_el is not None:
                num_map[num_id] = abstract.get(abstract_el.get(w("val"), ""), {})
        return num_map

    def _page_setup(self) -> PageSetup:
        setup = PageSetup()
        sect = self.document.find(".//w:sectPr", NS)
        if sect is None:
            return setup
        size = sect.find("w:pgSz", NS)
        if size is not None:
            setup.width_mm = twips_to_mm(size.get(w("w")), 210.0)
            setup.height_mm = twips_to_mm(size.get(w("h")), 297.0)
            if size.get(w("orient")) == "landscape" and setup.width_mm < setup.height_mm:
                setup.width_mm, setup.height_mm = setup.height_mm, setup.width_mm
        margins = sect.find("w:pgMar", NS)
        if margins is not None:
            setup.top_mm = twips_to_mm(margins.get(w("top")), 15.0)
            setup.right_mm = twips_to_mm(margins.get(w("right")), 20.0)
            setup.bottom_mm = twips_to_mm(margins.get(w("bottom")), 18.0)
            setup.left_mm = twips_to_mm(margins.get(w("left")), 20.0)
            setup.header_mm = twips_to_mm(margins.get(w("header")), 8.0)
            setup.footer_mm = twips_to_mm(margins.get(w("footer")), 8.0)
        setup.title_page = sect.find("w:titlePg", NS) is not None
        for ref in sect.findall("w:headerReference", NS):
            target = self.document_rels.get(ref.get(r("id"), ""))
            if ref.get(w("type")) == "first":
                setup.first_header_target = target
            elif ref.get(w("type")) == "default":
                setup.default_header_target = target
        for ref in sect.findall("w:footerReference", NS):
            target = self.document_rels.get(ref.get(r("id"), ""))
            if ref.get(w("type")) == "first":
                setup.first_footer_target = target
            elif ref.get(w("type")) == "default":
                setup.default_footer_target = target
        return setup

    def _style_chain(self, style_id: str | None) -> list[dict[str, ET.Element | str | None]]:
        chain: list[dict[str, ET.Element | str | None]] = []
        seen: set[str] = set()
        current = style_id
        while current and current not in seen and current in self.styles:
            seen.add(current)
            item = self.styles[current]
            chain.insert(0, item)
            current = item.get("based_on") if isinstance(item.get("based_on"), str) else None
        if "__default__" in self.styles:
            chain.insert(0, self.styles["__default__"])
        return chain

    @staticmethod
    def _merge_properties(elements: Iterable[ET.Element | None], child_name: str) -> ET.Element | None:
        found = None
        for element in elements:
            if element is None:
                continue
            child = element.find(f"w:{child_name}", NS)
            if child is not None:
                found = child
        return found

    def _paragraph_css(self, paragraph: ET.Element) -> tuple[str, str]:
        ppr = paragraph.find("w:pPr", NS)
        style_el = ppr.find("w:pStyle", NS) if ppr is not None else None
        style_id = style_el.get(w("val")) if style_el is not None else None
        style_chain = self._style_chain(style_id)
        pprs = [item.get("pPr") if isinstance(item, dict) else None for item in style_chain]
        if ppr is not None:
            pprs.append(ppr)

        css: list[str] = []
        classes: list[str] = ["word-paragraph"]
        align = self._merge_properties(pprs, "jc")
        if align is not None:
            value = align.get(w("val"), "left")
            css.append(f"text-align:{'justify' if value in {'both','distribute'} else value}")
        spacing = self._merge_properties(pprs, "spacing")
        if spacing is not None:
            before = twips_to_pt(spacing.get(w("before")))
            after = twips_to_pt(spacing.get(w("after")))
            css.extend([f"margin-top:{before:.2f}pt", f"margin-bottom:{after:.2f}pt"])
            line = spacing.get(w("line"))
            rule = spacing.get(w("lineRule"), "auto")
            if line:
                if rule == "auto":
                    css.append(f"line-height:{max(int(line) / 240.0, 0.8):.3f}")
                else:
                    css.append(f"line-height:{twips_to_pt(line):.2f}pt")
        indent = self._merge_properties(pprs, "ind")
        if indent is not None:
            left = twips_to_pt(indent.get(w("left")) or indent.get(w("start")))
            right = twips_to_pt(indent.get(w("right")) or indent.get(w("end")))
            first = twips_to_pt(indent.get(w("firstLine")))
            hanging = twips_to_pt(indent.get(w("hanging")))
            if left:
                css.append(f"margin-left:{left:.2f}pt")
            if right:
                css.append(f"margin-right:{right:.2f}pt")
            if first:
                css.append(f"text-indent:{first:.2f}pt")
            elif hanging:
                css.append(f"text-indent:-{hanging:.2f}pt")
        p_borders = self._merge_properties(pprs, "pBdr")
        if p_borders is not None:
            for side in ("top", "right", "bottom", "left"):
                border = p_borders.find(f"w:{side}", NS)
                if border is None or border.get(w("val")) in {None, "nil", "none"}:
                    continue
                size = max(int(border.get(w("sz"), "4")) / 8.0, 0.25)
                color = border.get(w("color"), "444444")
                color = "444444" if color == "auto" else color
                css.append(f"border-{side}:{size:.2f}pt solid #{color}")
                space = twips_to_pt(border.get(w("space")))
                if space:
                    css.append(f"padding-{side}:{space:.2f}pt")
        if any(self._merge_properties(pprs, name) is not None for name in ("keepNext", "keepLines")):
            css.append("break-inside:avoid")
        if self._merge_properties(pprs, "pageBreakBefore") is not None:
            classes.append("page-break-before")

        style_name = ""
        if style_id and style_id in self.styles:
            style_name = str(self.styles[style_id].get("name") or "")
            safe_name = re.sub(r"[^a-z0-9_-]+", "-", style_name.lower()).strip("-")
            if safe_name:
                classes.append(f"style-{safe_name}")
        return ";".join(css), " ".join(classes)

    def _run_css(self, run: ET.Element, paragraph: ET.Element | None = None) -> str:
        rpr = run.find("w:rPr", NS)
        ppr = paragraph.find("w:pPr", NS) if paragraph is not None else None
        p_style_el = ppr.find("w:pStyle", NS) if ppr is not None else None
        p_style_id = p_style_el.get(w("val")) if p_style_el is not None else None
        r_style_el = rpr.find("w:rStyle", NS) if rpr is not None else None
        r_style_id = r_style_el.get(w("val")) if r_style_el is not None else None

        rprs: list[ET.Element | None] = []
        for item in self._style_chain(p_style_id):
            rprs.append(item.get("rPr") if isinstance(item, dict) else None)
        for item in self._style_chain(r_style_id):
            rprs.append(item.get("rPr") if isinstance(item, dict) else None)
        if rpr is not None:
            rprs.append(rpr)

        css: list[str] = []
        fonts = self._merge_properties(rprs, "rFonts")
        if fonts is not None:
            font = fonts.get(w("ascii")) or fonts.get(w("hAnsi")) or fonts.get(w("cs"))
            if font:
                css.append(f"font-family:{css_escape_font(font)},Aptos,'Segoe UI',Arial,sans-serif")
        size = self._merge_properties(rprs, "sz")
        if size is not None:
            css.append(f"font-size:{half_points_to_pt(size.get(w('val'))):.2f}pt")
        if any(on_off(self._merge_properties(rprs, name)) for name in ("b", "bCs")):
            css.append("font-weight:700")
        if any(on_off(self._merge_properties(rprs, name)) for name in ("i", "iCs")):
            css.append("font-style:italic")
        underline = self._merge_properties(rprs, "u")
        strike = self._merge_properties(rprs, "strike")
        decorations: list[str] = []
        if underline is not None and underline.get(w("val"), "single") not in {"none", "0"}:
            decorations.append("underline")
        if on_off(strike):
            decorations.append("line-through")
        if decorations:
            css.append(f"text-decoration:{' '.join(decorations)}")
        color = self._merge_properties(rprs, "color")
        if color is not None:
            value = color.get(w("val"))
            if value and value not in {"auto", "none"}:
                css.append(f"color:#{value}")
        highlight = self._merge_properties(rprs, "highlight")
        if highlight is not None:
            mapping = {"yellow": "#fff59d", "green": "#b9f6ca", "cyan": "#b2ebf2", "magenta": "#f8bbd0", "blue": "#bbdefb", "red": "#ffcdd2", "darkYellow": "#ffe082", "gray25": "#e0e0e0"}
            value = highlight.get(w("val"), "")
            if value in mapping:
                css.append(f"background:{mapping[value]}")
        if on_off(self._merge_properties(rprs, "caps")):
            css.append("text-transform:uppercase")
        if on_off(self._merge_properties(rprs, "smallCaps")):
            css.append("font-variant:small-caps")
        vert = self._merge_properties(rprs, "vertAlign")
        if vert is not None:
            value = vert.get(w("val"))
            if value == "superscript":
                css.extend(["vertical-align:super", "font-size:75%"])
            elif value == "subscript":
                css.extend(["vertical-align:sub", "font-size:75%"])
        return ";".join(css)

    def _image_html(self, run: ET.Element, rels: dict[str, str], base_dir: str) -> str:
        blip = run.find(".//a:blip", NS)
        rel_id = blip.get(r("embed")) if blip is not None else None
        if not rel_id:
            image_data = run.find(".//v:imagedata", NS)
            rel_id = image_data.get(r("id")) if image_data is not None else None
        if not rel_id or rel_id not in rels:
            return ""
        target = rels[rel_id]
        member = posixpath.normpath(posixpath.join(base_dir, target))
        if member.startswith("../"):
            member = posixpath.normpath(posixpath.join(base_dir, target))
        if member not in self.archive.namelist():
            return ""
        data = self.archive.read(member)
        mime = mimetypes.guess_type(member)[0] or "application/octet-stream"
        width = None
        extent = run.find(".//wp:extent", NS)
        if extent is not None and extent.get("cx"):
            try:
                width = int(extent.get("cx", "0")) / 914400 * 96
            except ValueError:
                width = None
        style = f"max-width:{width:.0f}px" if width else "max-width:100%"
        encoded = base64.b64encode(data).decode("ascii")
        return f'<img class="word-image" style="{style}" src="data:{mime};base64,{encoded}" alt="">'

    def _run_tokens(self, run: ET.Element, paragraph: ET.Element, rels: dict[str, str], base_dir: str) -> list[str | None]:
        css = self._run_css(run, paragraph)
        pieces: list[str] = []
        tokens: list[str | None] = []

        def flush() -> None:
            if pieces:
                content = "".join(pieces)
                tokens.append(f'<span style="{css}">{content}</span>' if css else f"<span>{content}</span>")
                pieces.clear()

        image = self._image_html(run, rels, base_dir)
        for child in list(run):
            if child.tag == w("t"):
                pieces.append(html.escape(child.text or "").replace("\u00a0", "&nbsp;"))
            elif child.tag == w("tab"):
                pieces.append('<span class="word-tab-marker"></span>')
            elif child.tag == w("br"):
                break_type = child.get(w("type"))
                if break_type == "page":
                    flush()
                    tokens.append(None)
                else:
                    pieces.append("<br>")
            elif child.tag == w("lastRenderedPageBreak"):
                flush()
                tokens.append(None)
            elif child.tag in {w("drawing"), w("pict")}:
                pieces.append(image)
            elif child.tag == w("noBreakHyphen"):
                pieces.append("&#8209;")
            elif child.tag == w("softHyphen"):
                pieces.append("&shy;")
            elif child.tag == w("sym"):
                code = child.get(w("char"), "")
                try:
                    pieces.append(html.escape(chr(int(code, 16))))
                except (ValueError, OverflowError):
                    pass
            # fldChar and instrText are deliberately ignored; the displayed result
            # text is stored in ordinary w:t nodes in the following runs.
        flush()
        return tokens

    def _paragraph_segments(self, paragraph: ET.Element, rels: dict[str, str], base_dir: str) -> list[str | None]:
        p_css, p_classes = self._paragraph_css(paragraph)
        raw_tokens: list[str | None] = []
        for child in list(paragraph):
            if child.tag == w("r"):
                raw_tokens.extend(self._run_tokens(child, paragraph, rels, base_dir))
            elif child.tag == w("hyperlink"):
                href = "#"
                rel_id = child.get(r("id"))
                if rel_id and rel_id in rels:
                    href = rels[rel_id]
                link_content: list[str] = []
                for run in child.findall("w:r", NS):
                    for token in self._run_tokens(run, paragraph, rels, base_dir):
                        if token is None:
                            if link_content:
                                raw_tokens.append(f'<a href="{html.escape(href, quote=True)}">{"".join(link_content)}</a>')
                                link_content = []
                            raw_tokens.append(None)
                        else:
                            link_content.append(token)
                if link_content:
                    raw_tokens.append(f'<a href="{html.escape(href, quote=True)}">{"".join(link_content)}</a>')
            elif child.tag == w("fldSimple"):
                for run in child.findall(".//w:r", NS):
                    raw_tokens.extend(self._run_tokens(run, paragraph, rels, base_dir))

        prefix = self._number_prefix(paragraph)
        parts: list[str | None] = []
        current: list[str] = []
        for token in raw_tokens:
            if token is None:
                content = "".join(current)
                parts.append(self._wrap_paragraph(content, p_css, p_classes, prefix))
                parts.append(None)
                current = []
                prefix = ""
            else:
                current.append(token)
        content = "".join(current)
        parts.append(self._wrap_paragraph(content, p_css, p_classes, prefix))
        return parts

    @staticmethod
    def _wrap_paragraph(content: str, css: str, classes: str, prefix: str = "") -> str:
        content = prefix + content
        if '<span class="word-tab-marker"></span>' in content:
            segments = content.split('<span class="word-tab-marker"></span>')
            if len(segments) > 1:
                content = '<span class="word-tab-row">' + "".join(f"<span>{segment}</span>" for segment in segments) + "</span>"
        if not content:
            content = "&nbsp;"
        return f'<p class="{classes}" style="{css}">{content}</p>'

    def _number_prefix(self, paragraph: ET.Element) -> str:
        ppr = paragraph.find("w:pPr", NS)
        numpr = ppr.find("w:numPr", NS) if ppr is not None else None
        if numpr is None:
            return ""
        num_id_el = numpr.find("w:numId", NS)
        level_el = numpr.find("w:ilvl", NS)
        if num_id_el is None:
            return ""
        num_id = num_id_el.get(w("val"), "0")
        level = int(level_el.get(w("val"), "0")) if level_el is not None else 0
        fmt, pattern, start = self.numbering.get(num_id, {}).get(level, ("decimal", f"%{level + 1}.", 1))
        key = (num_id, level)
        if key not in self.list_counters:
            self.list_counters[key] = start
        else:
            self.list_counters[key] += 1
        value = self.list_counters[key]
        if fmt in {"bullet", "none"}:
            text = "•" if fmt == "bullet" else ""
        elif fmt == "lowerLetter":
            text = chr(96 + ((value - 1) % 26) + 1)
        elif fmt == "upperLetter":
            text = chr(64 + ((value - 1) % 26) + 1)
        elif fmt == "lowerRoman":
            text = self._roman(value).lower()
        elif fmt == "upperRoman":
            text = self._roman(value)
        else:
            text = str(value)
        rendered = pattern.replace(f"%{level + 1}", text)
        return f'<span class="word-list-prefix">{html.escape(rendered)}&nbsp;</span>'

    @staticmethod
    def _roman(value: int) -> str:
        pairs = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
        result = []
        for number, symbol in pairs:
            while value >= number:
                result.append(symbol)
                value -= number
        return "".join(result)

    def _cell_css(self, cell: ET.Element) -> tuple[str, int, int]:
        tcpr = cell.find("w:tcPr", NS)
        css: list[str] = []
        colspan = 1
        rowspan = 1
        if tcpr is not None:
            width = tcpr.find("w:tcW", NS)
            if width is not None and width.get(w("type")) == "dxa":
                css.append(f"width:{twips_to_pt(width.get(w('w'))):.2f}pt")
            shade = tcpr.find("w:shd", NS)
            if shade is not None:
                fill = shade.get(w("fill"))
                if fill and fill not in {"auto", "nil"}:
                    css.append(f"background:#{fill}")
            valign = tcpr.find("w:vAlign", NS)
            if valign is not None:
                mapping = {"center": "middle", "bottom": "bottom", "top": "top"}
                css.append(f"vertical-align:{mapping.get(valign.get(w('val'), 'top'), 'top')}")
            gridspan = tcpr.find("w:gridSpan", NS)
            if gridspan is not None:
                try:
                    colspan = max(1, int(gridspan.get(w("val"), "1")))
                except ValueError:
                    colspan = 1
            margins = tcpr.find("w:tcMar", NS)
            if margins is not None:
                for side in ("top", "right", "bottom", "left"):
                    item = margins.find(f"w:{side}", NS)
                    if item is not None:
                        css.append(f"padding-{side}:{twips_to_pt(item.get(w('w'))):.2f}pt")
            borders = tcpr.find("w:tcBorders", NS)
            if borders is not None:
                for side in ("top", "right", "bottom", "left"):
                    border = borders.find(f"w:{side}", NS)
                    if border is None or border.get(w("val")) in {None, "nil", "none"}:
                        continue
                    size = max(int(border.get(w("sz"), "4")) / 8.0, 0.25)
                    color = border.get(w("color"), "C7CCD1")
                    color = "C7CCD1" if color == "auto" else color
                    css.append(f"border-{side}:{size:.2f}pt solid #{color}")
        return ";".join(css), colspan, rowspan

    def _render_table(self, table: ET.Element, rels: dict[str, str], base_dir: str) -> str:
        tblpr = table.find("w:tblPr", NS)
        css: list[str] = ["border-collapse:collapse", "width:100%"]
        if tblpr is not None:
            width = tblpr.find("w:tblW", NS)
            if width is not None:
                if width.get(w("type")) == "pct":
                    try:
                        css.append(f"width:{int(width.get(w('w'), '5000')) / 50:.2f}%")
                    except ValueError:
                        pass
                elif width.get(w("type")) == "dxa":
                    css.append(f"width:{twips_to_pt(width.get(w('w'))):.2f}pt")
            align = tblpr.find("w:jc", NS)
            if align is not None:
                value = align.get(w("val"), "left")
                if value == "center":
                    css.extend(["margin-left:auto", "margin-right:auto"])
                elif value == "right":
                    css.extend(["margin-left:auto", "margin-right:0"])
            borders = tblpr.find("w:tblBorders", NS)
            if borders is not None:
                border = borders.find("w:insideH", NS) or borders.find("w:top", NS)
                if border is not None and border.get(w("val")) not in {None, "nil", "none"}:
                    size = max(int(border.get(w("sz"), "4")) / 8.0, 0.25)
                    color = border.get(w("color"), "C7CCD1")
                    color = "C7CCD1" if color == "auto" else color
                    css.append(f"--word-table-border:{size:.2f}pt solid #{color}")
        rows_html: list[str] = []
        for row in table.findall("w:tr", NS):
            cells_html: list[str] = []
            for cell in row.findall("w:tc", NS):
                cell_css, colspan, rowspan = self._cell_css(cell)
                blocks = self._render_blocks(list(cell), rels, base_dir, allow_page_breaks=False)
                attrs = [f'style="{cell_css}"']
                if colspan > 1:
                    attrs.append(f'colspan="{colspan}"')
                if rowspan > 1:
                    attrs.append(f'rowspan="{rowspan}"')
                cells_html.append(f'<td {" ".join(attrs)}>{"".join(blocks[0])}</td>')
            rows_html.append(f'<tr>{"".join(cells_html)}</tr>')
        return f'<table class="word-table" style="{";".join(css)}"><tbody>{"".join(rows_html)}</tbody></table>'

    def _render_blocks(self, children: list[ET.Element], rels: dict[str, str], base_dir: str, *, allow_page_breaks: bool = True) -> list[list[str]]:
        pages: list[list[str]] = [[]]
        for child in children:
            if child.tag == w("sectPr"):
                continue
            if child.tag == w("p"):
                segments = self._paragraph_segments(child, rels, base_dir)
                for segment in segments:
                    if segment is None and allow_page_breaks:
                        if pages[-1]:
                            pages.append([])
                    elif segment is not None:
                        pages[-1].append(segment)
            elif child.tag == w("tbl"):
                pages[-1].append(self._render_table(child, rels, base_dir))
            elif child.tag == w("sdt"):
                content = child.find("w:sdtContent", NS)
                if content is not None:
                    nested = self._render_blocks(list(content), rels, base_dir, allow_page_breaks=allow_page_breaks)
                    pages[-1].extend(nested[0])
                    for additional in nested[1:]:
                        pages.append(additional)
        while len(pages) > 1 and not pages[-1]:
            pages.pop()
        return pages

    def _part_rels(self, target: str) -> tuple[dict[str, str], str]:
        member = target if target.startswith("word/") else f"word/{target}"
        member = posixpath.normpath(member)
        base_dir = posixpath.dirname(member)
        rel_member = posixpath.join(base_dir, "_rels", posixpath.basename(member) + ".rels")
        return self._load_rels(rel_member), base_dir

    def _render_header(self, target: str | None) -> str:
        if not target:
            return ""
        member = target if target.startswith("word/") else f"word/{target}"
        member = posixpath.normpath(member)
        if member not in self.archive.namelist():
            return ""
        root = self._xml(member)
        rels, base_dir = self._part_rels(target)
        blocks = self._render_blocks(list(root), rels, base_dir, allow_page_breaks=False)[0]
        return "".join(blocks)

    def _body_pages(self) -> list[list[str]]:
        body = self.document.find("w:body", NS)
        if body is None:
            return [[]]
        return self._render_blocks(list(body), self.document_rels, "word", allow_page_breaks=True)

    def render(self, *, title: str | None = None, download_url: str = "", auto_print: bool = False) -> str:
        explicit_pages = self._body_pages()
        first_header = self._render_header(self.setup.first_header_target if self.setup.title_page else self.setup.default_header_target)
        default_header = self._render_header(self.setup.default_header_target or self.setup.first_header_target)
        safe_title = html.escape(title or self.filename)
        safe_filename = html.escape(self.filename)

        source_html = "".join(
            f'<div class="word-explicit-page">{"".join(blocks)}</div>'
            for blocks in explicit_pages
        )
        top = max(self.setup.top_mm, 19.0)
        bottom = max(self.setup.bottom_mm, 17.0)
        left = max(self.setup.left_mm, 12.0)
        right = max(self.setup.right_mm, 12.0)
        download_button = f'<a class="toolbar-btn" href="{html.escape(download_url, quote=True)}">Descarcă Word</a>' if download_url else ""
        auto_js = "setTimeout(() => window.print(), 850);" if auto_print else ""
        return f'''<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} · tipărire</title>
<style>
:root{{--page-width:{self.setup.width_mm:.3f}mm;--page-height:{self.setup.height_mm:.3f}mm;--page-top:{top:.3f}mm;--page-right:{right:.3f}mm;--page-bottom:{bottom:.3f}mm;--page-left:{left:.3f}mm}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0;background:#e9ecef;color:#202326;font-family:Aptos,'Segoe UI',Arial,sans-serif}}
.print-toolbar{{position:sticky;top:0;z-index:1000;display:flex;align-items:center;gap:10px;padding:12px 18px;background:#20252a;color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.24)}}
.print-toolbar strong{{margin-right:auto;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.print-toolbar small{{opacity:.78}}
.toolbar-btn{{border:1px solid rgba(255,255,255,.34);border-radius:7px;background:#fff;color:#20252a;padding:8px 12px;text-decoration:none;font:600 13px Aptos,'Segoe UI',Arial,sans-serif;cursor:pointer}}
.toolbar-btn.primary{{background:#1684dc;color:#fff;border-color:#1684dc}}
.print-help{{max-width:var(--page-width);margin:16px auto 0;padding:10px 14px;background:#fff8db;border:1px solid #edd782;border-radius:8px;font-size:12px;line-height:1.45}}
.word-source{{position:absolute;left:-100000px;top:0;width:calc(var(--page-width) - var(--page-left) - var(--page-right));visibility:hidden}}
.word-pages{{padding-bottom:18px}}
.word-page{{position:relative;width:var(--page-width);height:var(--page-height);margin:16px auto;background:#fff;box-shadow:0 4px 18px rgba(0,0,0,.22);overflow:hidden;break-after:page;page-break-after:always}}
.word-page:last-child{{break-after:auto;page-break-after:auto}}
.word-page-header{{position:absolute;top:{self.setup.header_mm:.3f}mm;left:var(--page-left);right:var(--page-right);min-height:8mm}}
.word-page-body{{position:absolute;top:var(--page-top);right:var(--page-right);bottom:var(--page-bottom);left:var(--page-left);overflow:hidden;font-size:11pt;line-height:1.12}}
.word-page-footer{{position:absolute;left:var(--page-left);right:var(--page-right);bottom:{self.setup.footer_mm:.3f}mm;display:flex;justify-content:space-between;align-items:flex-end;border-bottom:.25pt solid #343434;padding-bottom:2.5mm;color:#555a5f;font-size:8pt;white-space:nowrap}}
.word-paragraph{{margin:0 0 6pt 0;white-space:normal;overflow-wrap:break-word}}
.word-tab-row{{display:flex;width:100%;justify-content:space-between;align-items:baseline;gap:10mm}}
.word-tab-row>span{{min-width:0}}
.word-list-prefix{{display:inline-block;min-width:1.8em}}
.word-table{{margin:4pt 0 7pt 0;font-size:inherit;break-inside:avoid}}
.word-table td{{border:var(--word-table-border,.25pt solid #c7ccd1);padding:3pt 5pt;vertical-align:top}}
.word-table .word-paragraph{{margin-bottom:0}}
.word-image{{height:auto;vertical-align:middle}}
.style-title,.style-titlu{{font-weight:700}}
.page-break-before{{break-before:page}}
a{{color:inherit}}
@page{{size:{self.setup.width_mm:.3f}mm {self.setup.height_mm:.3f}mm;margin:0}}
@media print{{
  html,body{{background:#fff}}
  .print-toolbar,.print-help,.word-source{{display:none!important}}
  .word-pages{{padding:0}}
  .word-page{{margin:0;box-shadow:none;width:var(--page-width);height:var(--page-height)}}
}}
@media(max-width:850px){{.print-toolbar small{{display:none}}}}
</style>
</head>
<body>
<div class="print-toolbar"><strong>{safe_title}</strong><small>Previzualizare Word în browser</small>{download_button}<button class="toolbar-btn primary" onclick="window.print()">Tipărește / Salvează PDF</button><button class="toolbar-btn" onclick="window.close()">Închide</button></div>
<div class="print-help">În fereastra de tipărire alegeți destinația <b>Save as PDF / Salvează ca PDF</b>. Pentru redare identică motorului Microsoft Word, descărcați DOCX-ul și folosiți în Word <b>Fișier → Salvare ca → PDF</b>.</div>
<template id="firstHeaderTemplate">{first_header}</template>
<template id="defaultHeaderTemplate">{default_header}</template>
<div id="wordSource" class="word-source">{source_html}</div>
<div id="wordPages" class="word-pages" aria-label="Previzualizare document"></div>
<script>
const WORD_FILENAME={safe_filename!r};
function makePage(isFirst){{
  const page=document.createElement('section'); page.className='word-page';
  const header=document.createElement('header'); header.className='word-page-header';
  const headerTemplate=document.getElementById(isFirst?'firstHeaderTemplate':'defaultHeaderTemplate');
  header.innerHTML=headerTemplate.innerHTML;
  const body=document.createElement('main'); body.className='word-page-body';
  const footer=document.createElement('footer'); footer.className='word-page-footer';
  footer.innerHTML=`<span>${{WORD_FILENAME}}</span><span class="page-label"></span>`;
  page.append(header,body,footer); document.getElementById('wordPages').append(page);
  return {{page,body,footer}};
}}
function overflows(body){{return body.scrollHeight>body.clientHeight+1}}
function cloneTableShell(table){{
  const clone=table.cloneNode(false);
  for(const child of [...table.children]){{
    if(child.tagName==='COLGROUP'||child.tagName==='THEAD') clone.append(child.cloneNode(true));
  }}
  const tbody=document.createElement('tbody'); clone.append(tbody); return {{table:clone,tbody}};
}}
function paginateWordDocument(){{
  const source=document.getElementById('wordSource');
  const groups=[...source.querySelectorAll(':scope > .word-explicit-page')];
  let current=makePage(true); let pageCount=1;
  const newPage=()=>{{current=makePage(false);pageCount++;return current}};
  function appendNormal(block){{
    current.body.append(block);
    if(overflows(current.body)){{
      current.body.removeChild(block); newPage(); current.body.append(block);
    }}
  }}
  function appendTable(original){{
    const rows=[...original.querySelectorAll(':scope > tbody > tr')];
    if(!rows.length){{appendNormal(original);return}}
    let shell=cloneTableShell(original); current.body.append(shell.table);
    rows.forEach((row,rowIndex)=>{{
      shell.tbody.append(row);
      if(overflows(current.body)){{
        shell.tbody.removeChild(row);
        if(shell.tbody.children.length===0){{
          shell.tbody.append(row);
          if(rowIndex<rows.length-1){{newPage();shell=cloneTableShell(original);current.body.append(shell.table)}}
          return;
        }}
        newPage(); shell=cloneTableShell(original); current.body.append(shell.table); shell.tbody.append(row);
      }}
    }});
  }}
  groups.forEach((group,index)=>{{
    if(index>0&&current.body.children.length) newPage();
    for(const block of [...group.children]){{
      if(block.classList.contains('page-break-before')&&current.body.children.length) newPage();
      if(block.tagName==='TABLE') appendTable(block); else appendNormal(block);
    }}
  }});
  const pages=[...document.querySelectorAll('.word-page')];
  pages.forEach((page,index)=>{{page.querySelector('.page-label').textContent=`Pagina ${{index+1}} | ${{pages.length}}`;}});
  source.remove();
}}
window.addEventListener('load',()=>{{paginateWordDocument();{auto_js}}});
</script>
</body>
</html>'''


def render_docx_for_print(source: Path, *, title: str | None = None, filename: str | None = None, download_url: str = "", auto_print: bool = False) -> str:
    with DocxPrintRenderer(source, filename=filename) as renderer:
        return renderer.render(title=title, download_url=download_url, auto_print=auto_print)
