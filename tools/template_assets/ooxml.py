"""Read trusted local T03 assets without executing or rewriting workbooks."""
from __future__ import annotations

import hashlib
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(node):
    if node is None:
        return None
    result = {"tag": node.tag.rsplit("}", 1)[-1], **node.attrib}
    if node.text and node.text.strip():
        result["text"] = node.text
    if len(node):
        result["children"] = [tree(x) for x in node]
    return result


def read_book(path: Path):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError("CORRUPT_WORKBOOK")
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = ["".join(t.text or "" for t in x.findall(".//m:t", NS))
                       for x in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        styles = ET.fromstring(z.read("xl/styles.xml"))
        formats = {int(x.attrib["numFmtId"]): x.attrib["formatCode"] for x in styles.findall("m:numFmts/m:numFmt", NS)}
        xfs = list(styles.find("m:cellXfs", NS))

        def style(index):
            xf = xfs[index]
            fmt_id = int(xf.attrib.get("numFmtId", 0))
            return {"font": tree(list(styles.find("m:fonts", NS))[int(xf.attrib.get("fontId", 0))]),
                    "fill": tree(list(styles.find("m:fills", NS))[int(xf.attrib.get("fillId", 0))]),
                    "border": tree(list(styles.find("m:borders", NS))[int(xf.attrib.get("borderId", 0))]),
                    "alignment": tree(xf.find("m:alignment", NS)),
                    "number_format": formats.get(fmt_id, {0: "General", 14: "mm-dd-yy"}.get(fmt_id, f"builtin:{fmt_id}"))}

        sheets = []
        for sh in wb.findall("m:sheets/m:sheet", NS):
            target = rels[sh.attrib[f"{{{REL}}}id"]]
            xml_path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            root = ET.fromstring(z.read(xml_path))
            cells, rows = {}, {}
            for row in root.findall("m:sheetData/m:row", NS):
                rows[int(row.attrib["r"])] = dict(row.attrib)
                for c in row.findall("m:c", NS):
                    t = c.attrib.get("t", "n")
                    value = c.findtext("m:v", default=None, namespaces=NS)
                    if t == "s" and value is not None:
                        value = strings[int(value)]
                    elif t == "inlineStr":
                        value = "".join(n.text or "" for n in c.findall("m:is/.//m:t", NS))
                    cells[c.attrib["r"]] = {"value": value, "type": t,
                        "formula": c.findtext("m:f", namespaces=NS), "style_index": int(c.attrib.get("s", 0))}
            sheets.append({"name": sh.attrib["name"], "cells": cells, "rows": rows,
                "merges": [n.attrib["ref"] for n in root.findall("m:mergeCells/m:mergeCell", NS)],
                "column_dimensions": [dict(c.attrib) for c in root.findall("m:cols/m:col", NS)],
                "pane": tree(root.find("m:sheetViews/m:sheetView/m:pane", NS)),
                "sheet_view": tree(root.find("m:sheetViews/m:sheetView", NS)),
                "tab_color": tree(root.find("m:sheetPr/m:tabColor", NS)),
                "page_setup": tree(root.find("m:pageSetup", NS)),
                "page_margins": tree(root.find("m:pageMargins", NS)),
                "styles": {addr: style(cells[addr]["style_index"]) for addr in ("A1", "A2", "A3", "B3", "D3", "G3", "P3") if addr in cells}})
        pr = wb.find("m:workbookPr", NS)
        return {"sha256": sha256(path), "date1904": pr is not None and pr.attrib.get("date1904") in ("1", "true"),
                "defined_names": [dict(n.attrib, text=n.text or "") for n in wb.findall("m:definedNames/m:definedName", NS)], "sheets": sheets}


def sheet_rows(sheet):
    """Fill country only inside explicit route merge bounds, never forward across groups."""
    cells = sheet["cells"]
    value = lambda col, row: cells.get(f"{col}{row}", {}).get("value")
    groups = []
    for merge in sheet["merges"]:
        match = re.fullmatch(r"A([3-9]|[1-9][0-9]+):A([1-9][0-9]*)", merge)
        if match:
            start, end = map(int, match.groups())
            groups.append((start, end, value("A", start)))
    # A one-row route need not be represented by an Excel merge.
    covered = {row for start, end, _ in groups for row in range(start, end + 1)}
    for row in sheet["rows"]:
        if row >= 3 and value("A", row) and row not in covered:
            groups.append((row, row, value("A", row)))
    result = []
    for start, end, route in sorted(groups):
        country_en = country_zh = None
        for row in range(start, end + 1):
            if value("B", row) or value("C", row):
                country_en, country_zh = value("B", row), value("C", row)
            if not value("D", row):
                continue
            if not country_en or not country_zh or not value("E", row):
                raise ValueError(f"INCOMPLETE_DESTINATION: {sheet['name']}!D{row}")
            result.append({"sheet": sheet["name"], "row": row, "route": route, "country_en": country_en,
                "country_zh": country_zh, "name_en": value("D", row), "name_zh": value("E", row),
                "values": {chr(65+i): value(chr(65+i), row) for i in range(18)}})
    actual = {int(re.search(r"[0-9]+$", a)[0]) for a,c in cells.items() if a.startswith("D") and a[1:].isdigit() and int(a[1:]) >= 3 and c["value"]}
    if actual != {r["row"] for r in result}:
        raise ValueError(f"DESTINATION_OUTSIDE_ROUTE: {sheet['name']}")
    return result
