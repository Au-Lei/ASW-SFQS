"""Extract versioned T03 assets from frozen v8 and a hash-locked v12 copy.

No workbook writer is used. Real prices are written ONLY under ignored private/.
This is a bootstrap asset tool, not the future production upload parser (T19).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.template_assets.ooxml import read_book, sha256, sheet_rows
from backend.app.domain.contracts import Destination, DestinationDirectory, QuotationValues
from backend.app.domain.template_layout import plan_sheet

PRIVATE = ROOT / "tests/fixtures/private/t03-v1"
V8 = ROOT / "tests/fixtures/private/t01-v1/raw/qingdao_template_v8.xlsx"
V12 = PRIVATE / "raw/quotation-v12.xlsx"
NS = UUID("8d6a8e25-882d-54b1-a68a-feb99bc173f9")


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).upper().split())


def key(row):
    return normalize(row["country_en"]) + "|" + normalize(row["name_en"])


def uid(kind, value):
    return str(uuid5(NS, kind + ":" + value))


def content_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest()


def source_ref(book, row):
    return {"file_sha256": book["sha256"], "sheet_name": row["sheet"], "cell_range": f"B{row['row']}:R{row['row']}"}


def compact_style(style):
    font = {n["tag"]: n for n in style["font"].get("children", [])}
    pattern = style["fill"].get("children", [{}])[0]
    colors = {n["tag"]: n for n in pattern.get("children", [])}
    fg = colors.get("fgColor", {}).get("rgb")
    alignment = style["alignment"] or {}
    return {"font": {"name": font.get("name", {}).get("val"), "size": float(font.get("sz", {}).get("val", 10)),
                     "bold": "b" in font, "color": font.get("color", {}).get("rgb")},
            "fill": fg, "number_format": style["number_format"],
            "alignment": {k: v for k,v in alignment.items() if k != "tag"},
            "borders": {n["tag"]: {"style": n.get("style"),
                "color": next((c.get("rgb") for c in n.get("children", []) if c["tag"] == "color"), None)}
                for n in style["border"].get("children", []) if n.get("style")}}


def extract_assets():
    manifest = json.loads((PRIVATE/"manifest.json").read_text(encoding="utf-8"))
    if sha256(V12) != manifest["sha256"]:
        raise ValueError("V12_FROZEN_HASH_MISMATCH")
    v8, v12 = read_book(V8), read_book(V12)
    columns = json.loads((ROOT / "config/quotation-columns-v1.json").read_text(encoding="utf-8"))
    names = columns["sheet_names"]
    for book in (v8, v12):
        if [s["name"] for s in book["sheets"]] != names:
            raise ValueError("SHEET_CONTRACT_MISMATCH")
        for sh in book["sheets"]:
            if [sh["cells"][c["letter"]+"2"]["value"] for c in columns["columns"]] != [c["label"] for c in columns["columns"]]:
                raise ValueError("COLUMN_CONTRACT_MISMATCH")
    base_rows = [r for sh in v8["sheets"] for r in sheet_rows(sh)]
    latest_rows = [r for sh in v12["sheets"] for r in sheet_rows(sh)]
    if any(r["values"].get(c) for r in base_rows for c in "FGHIJKLMNOPQR"):
        raise ValueError("V8_CONTAINS_QUOTATION_DATA")
    if len({key(r) for r in base_rows}) != len(base_rows):
        raise ValueError("BASE_DIRECTORY_DUPLICATE")
    countries, routes, regions, destinations = {}, {}, [], []
    # Only types explicitly identified in user requirements or the source label.
    explicit_inland = {("MEXICO", "MEXICO CITY"), ("MEXICO", "MONTERREY"), ("MEXICO", "GUADALAJARA"),
                       ("SOUTH AFRICA", "JOHANNESBURG"), ("SAUDI ARABIA", "RIYADH")}
    for i, sh in enumerate(v8["sheets"], 1):
        region_id = uid("region", sh["name"])
        regions.append({"id": region_id, "code": f"REGION_{i:02}", "name": sh["name"], "sort_order": i})
        for row in [r for r in base_rows if r["sheet"] == sh["name"]]:
            country_key = normalize(row["country_en"])
            country_id = uid("country-region", country_key)
            if country_key in countries and countries[country_key]["name_zh"] != row["country_zh"]:
                raise ValueError("COUNTRY_NAME_CONFLICT")
            countries.setdefault(country_key, {"id": country_id, "name_en": row["country_en"], "name_zh": row["country_zh"]})
            route_key = sh["name"] + "|" + row["route"]
            if route_key not in routes:
                routes[route_key] = {"id": uid("route-group", route_key), "region_id": region_id,
                    "code": f"R{i:02}_{sum(r['region_id'] == region_id for r in routes.values())+1:02}",
                    "name": row["route"], "sort_order": sum(r["region_id"] == region_id for r in routes.values()) + 1}
            kind = "INLAND_POINT" if (row["country_en"], row["name_en"]) in explicit_inland else "UNKNOWN"
            if " ICD" in row["name_en"]:
                kind = "ICD"
            destinations.append({"id": uid("destination", key(row)), "canonical_key": key(row),
                "country_region_id": country_id, "kind": kind, "parent_destination_id": None,
                "display_name_en": row["name_en"], "display_name_zh": row["name_zh"],
                "route_group_id": routes[route_key]["id"], "version": 1, "active": True,
                "sort_order": sum(d["route_group_id"] == routes[route_key]["id"] for d in destinations) + 1,
                "source": source_ref(v8, row),
                "kind_basis": "EXPLICIT_USER_REQUIREMENT_OR_SOURCE_LABEL" if kind != "UNKNOWN" else "NOT_INFERRED_FROM_COLUMN_NAME"})
    fields = Destination.model_fields
    DestinationDirectory(destinations=[{k:v for k,v in d.items() if k in fields} for d in destinations])
    seeds = {"schema_version": "qingdao.seed.1", "namespace_uuid": str(NS), "source_sha256": v8["sha256"],
        "origin_ports": [{"id": uid("origin-port", "QINGDAO"), "display_name_en":"QINGDAO", "display_name_zh":"青岛港", "standard_code":None}],
        "regions":regions, "route_groups":list(routes.values()), "country_regions":list(countries.values()), "destinations":destinations}
    template = {"schema_version":"qingdao.template.1", "template_version":"qingdao-v1", "columns_config":"quotation-columns-v1.json",
        "source_sha256": v8["sha256"], "date_system":"1900", "title_merge":"A1:R1", "header_row":2, "first_data_row":3,
        "freeze":{"rows":2,"columns":5,"top_left_cell":"F3"},
        "country_display":{"first_row_only":True,"separator_rows":1,"reset_at_route_boundary":True,"merge_country_cells":False},
        "route_display":{"column":"A","merge":True,"separator_rows":1,"fill":"#CFF2CF"},
        "value_policy":{"missing":"BLANK","money_cell_type":"NUMBER","money_format":"#,##0.####",
                        "date_cell_type":"EXCEL_SERIAL_NUMBER","date_format":"mm-dd","source_unassigned":"BLANK"},
        "change_colors":{"CREATE":"#E2F0D9","UPDATE":"#FFF2CC","CONFLICT":"#FCE4D6"},
        "style_policy":"PRESERVE_V8_BASE_STYLE_DO_NOT_COPY_HISTORICAL_CHANGE_HIGHLIGHTS",
        "sheets":[]}
    for sh in v8["sheets"]:
        rid = uid("region", sh["name"])
        group_ids = {r["id"] for r in routes.values() if r["region_id"] == rid}
        rows = [d for d in destinations if d["route_group_id"] in group_ids]
        layout = plan_sheet(rows)
        observed_rows = [r["row"] for r in base_rows if r["sheet"] == sh["name"]]
        if [r["row"] for r in layout["rows"]] != observed_rows or layout["merges"] != sh["merges"]:
            raise ValueError(f"LAYOUT_REPLAY_MISMATCH: {sh['name']}")
        styles = {name: compact_style(sh["styles"][addr]) for name,addr in
                  {"title":"A1","header":"A2","route":"A3","country":"B3","body":"D3","money":"G3","date":"P3"}.items()}
        styles["date"]["number_format"] = "mm-dd"
        styles["money"]["number_format"] = "#,##0.####"
        template["sheets"].append({"name":sh["name"],"region_id":rid,"title":sh["cells"]["A1"]["value"],
            "route_group_ids":[r["id"] for r in routes.values() if r["region_id"] == rid],
            "column_dimensions":sh["column_dimensions"],"show_grid_lines":False,"tab_color":sh["tab_color"],
            "row_heights":{"title":float(sh["rows"][1]["ht"]),"header":float(sh["rows"][2]["ht"]),
                "body":float(sh["rows"][layout["rows"][0]["row"]]["ht"]),
                "separator":float(sh["rows"][layout["separator_rows"][0]]["ht"]) if layout["separator_rows"] else None},
            "styles":styles,"wrap_columns":["A","M","O","R"],"page_margins":sh["page_margins"],
            "page_setup":sh["page_setup"],"print_policy":"PRESERVE_UNSPECIFIED_NO_FORCED_PAPER_SIZE",
            "baseline_layout":layout})
    a = {key(r):r for r in base_rows}
    b = {key(r):r for r in latest_rows}
    baseline_routes = {(r["sheet"],r["route"]) for r in base_rows}
    added_routes = list(dict.fromkeys((r["sheet"],r["route"]) for r in latest_rows if (r["sheet"],r["route"]) not in baseline_routes))
    def describe(r):
        return {"canonical_key":key(r), "country_en":r["country_en"], "country_zh":r["country_zh"],
                "name_en":r["name_en"], "name_zh":r["name_zh"], "sheet":r["sheet"], "route":r["route"], "row":r["row"]}
    diff = {"schema_version":"qingdao.directory-diff.1", "v8_sha256":v8["sha256"], "v12_sha256":v12["sha256"],
        "summary":{"baseline_destination_rows":len(base_rows),"latest_destination_rows":len(latest_rows),"latest_distinct_keys":len(b),
                   "common_keys":len(a.keys() & b.keys()),"added_keys":len(b.keys()-a.keys()),"absent_baseline_keys":len(a.keys()-b.keys()),
                   "extra_quote_rows_same_destination":len(latest_rows)-len(b),"baseline_route_groups":len(routes),"added_route_groups":len(added_routes)},
        "added":[describe(r) for k,r in b.items() if k not in a],
        "absent_from_v12":[{**describe(r),"decision":"KEEP_PARENT_IDENTITY_NO_IMPLICIT_DELETE"} for k,r in a.items() if k not in b],
        "moved":[{"old":describe(a[k]),"new":describe(b[k])} for k in a.keys() & b.keys() if (a[k]["sheet"],a[k]["route"]) != (b[k]["sheet"],b[k]["route"])],
        "renamed_zh":[{"old":describe(a[k]),"new":describe(b[k])} for k in sorted(a.keys() & b.keys()) if a[k]["name_zh"] != b[k]["name_zh"]],
        "added_route_groups":[{"sheet":s,"name":r,"id":uid("route-group",s+"|"+r),"status":"MIGRATION_PROPOSAL"} for s,r in added_routes],
        "duplicate_destination_rows":[{"canonical_key":k,"rows":[describe(r) for r in latest_rows if key(r)==k],"decision":"ONE_DESTINATION_MULTIPLE_QUOTES_KEEP_BOTH"}
            for k,n in Counter(key(r) for r in latest_rows).items() if n>1],
        "identity_decisions":[{"parent_key":"EGYPT|ALEXANDRIA", "child_keys":["EGYPT|ALEXANDRIA (ABU QIR)","EGYPT|ALEXANDRIA (TMT)"],
            "decision":"PROPOSE_TERMINAL_CHILDREN_RETAIN_PARENT_NO_PARENT_PRICE_FANOUT"}],
        "activation_policy":"DO_NOT_AUTO_ACTIVATE_V12_ADDITIONS_OR_APPLY_QUOTES_IN_T03"}
    candidates = []
    for row in latest_rows:
        vals = row["values"]
        if not any(vals[c] is not None for c in "GHI"):
            continue
        def full_date(col):
            raw = vals[col]
            if raw is None:
                return None
            cell = next(s for s in v12["sheets"] if s["name"] == row["sheet"])["cells"][col+str(row["row"])]
            if cell["type"] == "d":
                return date.fromisoformat(raw[:10]).isoformat()
            if v12["date1904"]:
                return (date(1904,1,1)+timedelta(days=int(raw))).isoformat()
            # The frozen files use modern Excel 1900-system dates after its leap-year quirk.
            return (date(1899,12,30)+timedelta(days=int(raw))).isoformat()
        q = QuotationValues(origin_port_id=uid("origin-port","QINGDAO"), destination_id=uid("destination",key(row)) if key(row) in a else None,
            price_20gp=vals["G"],price_40gp=vals["H"],price_40hq=vals["I"],currency=vals["J"],source_code=vals["N"],
            validity={"valid_from":full_date("P"),"valid_to":full_date("Q"),"basis":"UNSPECIFIED"},
            remarks=vals["O"],price_scope_summary=vals["R"],schedule={"raw_text":vals["K"],"transit_days_raw":vals["L"]},routing={"raw_text":vals["M"]})
        candidates.append({"fixture_key":f"v12:{row['sheet']}:{row['row']}","destination_key":key(row),"destination_proposal":describe(row),
            "historical_carrier_code_raw":vals["F"],"source":source_ref(v12,row),"raw_values":vals,
            "normalized_payload":q.model_dump(mode="json"), "review_state":"PENDING_REVIEW","application_state":"NOT_APPLIED",
            "match_state":"SUGGESTED" if key(row) in a else "UNMATCHED",
            "historical_approval_context":"PRIOR_USER_APPROVAL_EXISTS_RECONCILE_ORIGINAL_EVIDENCE_IN_T08",
            "origin_evidence":{"file_sha256":v12["sha256"],"sheet_name":row["sheet"],"cell_range":"A1"},
            "destination_status":"BASE_DIRECTORY_MATCH" if key(row) in a else "ADDITION_REQUIRES_MIGRATION_REVIEW"})
    inventory = {"sheets":[{"name":sh["name"],"baseline_destinations":sum(r["sheet"]==sh["name"] for r in base_rows),
        "latest_rows":sum(r["sheet"]==sh["name"] for r in latest_rows), "priced_rows":sum(c["source"]["sheet_name"]==sh["name"] for c in candidates)} for sh in v8["sheets"]],
        "summary":diff["summary"],"migration_quote_candidates":len(candidates),"blank_placeholder_rows":len(latest_rows)-len(candidates),
        "kind_counts":dict(Counter(d["kind"] for d in destinations))}
    seeds["content_sha256"] = content_hash(seeds)
    template["seed_content_sha256"] = seeds["content_sha256"]
    template["content_sha256"] = content_hash(template)
    products = {ROOT/"config/seeds/qingdao-v1.json":seeds, ROOT/"config/template-qingdao-v1.json":template,
                ROOT/"config/migrations/v8-v12-directory-diff.json":diff, ROOT/"config/migrations/t03-inventory.json":inventory,
                PRIVATE/"migration-candidates.json":{"schema_version":"t03.migration-candidates.1","source_sha256":v12["sha256"],"candidates":candidates}}
    return products, inventory


def freeze_latest(source):
    V12.parent.mkdir(parents=True, exist_ok=True)
    if V12.exists():
        if sha256(V12) != sha256(source):
            raise ValueError("V12_FROZEN_SOURCE_CHANGED_REFUSE_OVERWRITE")
    else:
        shutil.copy2(source,V12)
    if sha256(V12) != sha256(source):
        raise ValueError("V12_COPY_HASH_MISMATCH")
    V12.chmod(stat.S_IREAD)
    manifest_path = PRIVATE/"manifest.json"
    manifest = {"fixture_id":"t03-v1", "role":"HISTORICAL_MIGRATION_CANDIDATES_NOT_GOLDEN_APPROVAL",
        "source_workspace_path":source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else str(source),
        "frozen_path":"raw/quotation-v12.xlsx", "sha256":sha256(V12), "bytes":V12.stat().st_size}
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved["sha256"] != manifest["sha256"]:
            raise ValueError("V12_MANIFEST_CHANGED_REFUSE_OVERWRITE")
    else:
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-v12", type=Path)
    parser.add_argument("--check",action="store_true")
    args = parser.parse_args()
    if args.freeze_v12:
        if args.check:
            parser.error("--check cannot freeze or write sources")
        freeze_latest(args.freeze_v12)
    if not V12.exists():
        raise SystemExit("Freeze v12 explicitly once with --freeze-v12 PATH")
    before = {p:sha256(p) for p in (V8,V12)}
    products, inventory = extract_assets()
    for path,data in products.items():
        text = json.dumps(data,ensure_ascii=False,indent=2)+"\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                raise SystemExit("STALE_ASSET: "+str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text,encoding="utf-8",newline="\n")
    if any(sha256(p) != h for p,h in before.items()):
        raise ValueError("READ_ONLY_SOURCE_CHANGED")
    print(json.dumps(inventory,ensure_ascii=False))


if __name__ == "__main__":
    main()
