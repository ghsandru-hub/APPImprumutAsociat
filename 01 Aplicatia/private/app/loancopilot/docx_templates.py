"""Fill the existing Word templates without flattening their runs or formatting."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.dom import minidom

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
TOKEN = re.compile(r"\|~([^|~]+)~\|")
INTEREST_TEMPLATE = "10_Fisa_calcul_dobanda_si_nota_contabila.docx"


def text(node) -> str:
    return "".join(t.firstChild.data if t.firstChild else "" for t in node.getElementsByTagNameNS(W, "t"))


def parts(archive):
    return [n for n in archive.namelist() if n.startswith("word/") and n.endswith(".xml")]


def fields(source: Path) -> list[str]:
    found = set()
    with zipfile.ZipFile(source) as archive:
        for name in parts(archive):
            doc = minidom.parseString(archive.read(name))
            for p in doc.getElementsByTagNameNS(W, "p"):
                found.update(TOKEN.findall(text(p)))
    return sorted(found)


def replace_paragraph(p, values):
    nodes = list(p.getElementsByTagNameNS(W, "t"))
    original = text(p)
    spans = []
    offset = 0
    for node in nodes:
        value = node.firstChild.data if node.firstChild else ""
        spans.append((node, offset, offset + len(value)))
        offset += len(value)
    # Work backwards so offsets before the current token stay valid.
    for match in reversed(list(TOKEN.finditer(original))):
        if match[1] not in values:
            continue
        inserted = False
        for node, start, end in spans:
            if end <= match.start() or start >= match.end():
                continue
            current = node.firstChild.data if node.firstChild else ""
            left = max(0, match.start() - start)
            right = min(end - start, match.end() - start)
            replacement = str(values[match[1]]) if not inserted else ""
            updated = current[:left] + replacement + current[right:]
            while node.firstChild:
                node.removeChild(node.firstChild)
            node.appendChild(node.ownerDocument.createTextNode(updated))
            node.setAttribute("xml:space", "preserve")
            inserted = True


def paragraph(doc, value, prototype=None):
    p = doc.createElementNS(W, "w:p")
    if prototype:
        for child in prototype.childNodes:
            if child.localName == "pPr":
                p.appendChild(child.cloneNode(True))
    r = doc.createElementNS(W, "w:r")
    for index, line in enumerate(str(value).split("\n")):
        if index:
            r.appendChild(doc.createElementNS(W, "w:br"))
        t = doc.createElementNS(W, "w:t")
        t.appendChild(doc.createTextNode(line))
        r.appendChild(t)
    p.appendChild(r)
    return p


def table(doc, headers, rows, widths):
    tbl = doc.createElementNS(W, "w:tbl")
    props = doc.createElementNS(W, "w:tblPr")
    borders = doc.createElementNS(W, "w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = doc.createElementNS(W, "w:" + side)
        for key, value in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
            edge.setAttributeNS(W, "w:" + key, value)
        borders.appendChild(edge)
    props.appendChild(borders)
    tbl.appendChild(props)
    grid = doc.createElementNS(W, "w:tblGrid")
    for width in widths:
        col = doc.createElementNS(W, "w:gridCol")
        col.setAttributeNS(W, "w:w", str(width))
        grid.appendChild(col)
    tbl.appendChild(grid)
    for i, values in enumerate([headers, *rows]):
        row = doc.createElementNS(W, "w:tr")
        row_props = doc.createElementNS(W, "w:trPr")
        row_props.appendChild(doc.createElementNS(W, "w:cantSplit"))
        if i == 0:
            row_props.appendChild(doc.createElementNS(W, "w:tblHeader"))
        row.appendChild(row_props)
        for j, value in enumerate(values):
            cell = doc.createElementNS(W, "w:tc")
            cell_props = doc.createElementNS(W, "w:tcPr")
            width = doc.createElementNS(W, "w:tcW")
            width.setAttributeNS(W, "w:w", str(widths[j]))
            width.setAttributeNS(W, "w:type", "dxa")
            cell_props.appendChild(width)
            if i == 0:
                shade = doc.createElementNS(W, "w:shd")
                shade.setAttributeNS(W, "w:fill", "E7EDF4")
                cell_props.appendChild(shade)
            cell.appendChild(cell_props)
            p = paragraph(doc, value)
            run = p.getElementsByTagNameNS(W, "r")[0]
            rp = doc.createElementNS(W, "w:rPr")
            size = doc.createElementNS(W, "w:sz")
            size.setAttributeNS(W, "w:val", "18")
            rp.appendChild(size)
            if i == 0:
                rp.appendChild(doc.createElementNS(W, "w:b"))
            run.insertBefore(rp, run.firstChild)
            cell.appendChild(p)
            row.appendChild(cell)
        tbl.appendChild(row)
    return tbl


def number(value):
    return f"{float(value or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def day(value):
    return ".".join(reversed(str(value or "").split("-")))


def interest_table(doc, rows):
    values = [[f"{day(r['period_start'])}\n– {day(r['period_end'])}",
               f"{r['contract_no']} · {r['associate_name']}", number(r['opening_balance']),
               number(r['closing_balance']), number(r['calculated_amount']), number(r['recognized_amount'])]
              for r in rows]
    values.append(["TOTAL", "", "", "", number(sum(r['calculated_amount'] for r in rows)),
                   number(sum(r['recognized_amount'] for r in rows))])
    return table(doc, ["Perioada", "Contract / creditor", "Sold început", "Sold final", "Calculată lei", "Recunoscută lei"],
                 values, [1450, 2200, 1150, 1150, 1150, 1150])


def prepare_interest_sheet(doc, rows, segments, values):
    """The shipped legacy sheet has fixed 2026 examples; replace those with selected data."""
    body = doc.getElementsByTagNameNS(W, "body")[0]
    children = [n for n in body.childNodes if n.nodeType == n.ELEMENT_NODE]
    title = next((n for n in children if n.localName == "p"), None)
    heading = next((n for n in children if n.localName == "p" and text(n).startswith("1.")), None)
    signature = next((n for n in reversed(children) if n.localName == "tbl" and "ÎNTOCMIT" in text(n)), None)
    section = next((n for n in children if n.localName == "sectPr"), None)
    for n in list(body.childNodes):
        body.removeChild(n)
    body.appendChild(paragraph(doc, "FIȘĂ DE CALCUL A DOBÂNZII ȘI NOTĂ CONTABILĂ", title))
    body.appendChild(paragraph(doc, f"{values.get('CompanieNume', '')} · CUI {values.get('CompanieCUI', '')}"))
    body.appendChild(paragraph(doc, f"Nr. {values.get('DocumentNumar', '')} din {values.get('DataCalcul', '')}"))
    body.appendChild(paragraph(doc, "1. Dobânzi trimestriale selectate", heading))
    body.appendChild(interest_table(doc, rows))
    body.appendChild(paragraph(doc, "Valorile sunt preluate din registrul Dobânzi trimestriale la data generării. Totalurile însumează liniile selectate, rotunjite la doi zecimale. Soldurile nu se cumulează între trimestre."))
    body.appendChild(paragraph(doc, "2. Subperioade și rate utilizate", heading))
    details = [[f"{s['contract_no']} · {s['associate_name']}", f"{day(s['segment_start'])} – {day(s['segment_end'])}",
                str(s['days']), number(s['rate']) + "%", number(s['balance_days']), number(s['calculated_amount'])]
               for s in segments]
    if details:
        body.appendChild(table(doc, ["Contract / creditor", "Interval", "Zile", "Rată anuală", "Sold zile", "Dobândă lei"],
                               details, [2100, 2100, 500, 1000, 1300, 1350]))
    else:
        body.appendChild(paragraph(doc, "Nu sunt înregistrate subperioade pentru liniile selectate."))
    body.appendChild(paragraph(doc, "Formula: sold zilnic × zile × rata anuală / 365. Ratele sunt cele păstrate în subperioadele calculului."))
    body.appendChild(paragraph(doc, "3. Note contabile", heading))
    notes = [[day(r['recognized_date'] or r['period_end']), f"Dobândă · {r['contract_no']} · {r['associate_name']}",
              "666 = 4558", number(r['recognized_amount'] if r['status'] == 'RECOGNIZED' else r['calculated_amount']),
              "Recunoscută" if r['status'] == 'RECOGNIZED' else "Propunere"] for r in rows]
    body.appendChild(table(doc, ["Data", "Operațiune", "Articol", "Sumă lei", "Stare"], notes, [1200, 3200, 1100, 1400, 1450]))
    if signature:
        body.appendChild(signature.cloneNode(True))
    else:
        body.appendChild(paragraph(doc, "ÎNTOCMIT: ____________________     VERIFICAT / APROBAT: ____________________"))
        body.appendChild(paragraph(doc, f"Data: {values.get('DataCalcul', '')}"))
    if section:
        body.appendChild(section.cloneNode(True))


def generate(source: Path, values: dict, rows: list[dict], segments: list[dict]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
        xml_parts = set(parts(archive))
        for info in archive.infolist():
            content = archive.read(info.filename)
            if info.filename in xml_parts:
                doc = minidom.parseString(content)
                if info.filename == "word/document.xml" and source.name == INTEREST_TEMPLATE:
                    prepare_interest_sheet(doc, rows, segments, values)
                for p in list(doc.getElementsByTagNameNS(W, "p")):
                    if "|~DobanziTrimestriale~|" in text(p):
                        if text(p).strip() != "|~DobanziTrimestriale~|" or p.parentNode.localName != "body":
                            raise ValueError("Marcajul DobanziTrimestriale trebuie să fie singur într-un paragraf în corpul documentului.")
                        p.parentNode.replaceChild(interest_table(doc, rows), p)
                    else:
                        replace_paragraph(p, values)
                content = doc.toxml(encoding="utf-8")
            result.writestr(info, content)
    return output.getvalue()
