"""Public directory/layout tests plus optional private migration replay."""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from collections import Counter
from pathlib import Path

from backend.app.domain.contracts import Destination, DestinationDirectory, QuotationValues
from backend.app.domain.template_layout import plan_sheet
from tools.template_assets.build_t03 import ROOT, V8, V12, PRIVATE, content_hash, extract_assets, key, normalize, uid
from tools.template_assets.ooxml import read_book, sheet_rows, sha256


def load(name):
    return json.loads((ROOT/name).read_text(encoding="utf-8"))


class PublicAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seeds = load("config/seeds/qingdao-v1.json")
        cls.template = load("config/template-qingdao-v1.json")
        cls.diff = load("config/migrations/v8-v12-directory-diff.json")
        cls.inventory = load("config/migrations/t03-inventory.json")

    def test_directory_counts(self):
        self.assertEqual(len(self.seeds["destinations"]),295)
        self.assertEqual(len(self.seeds["regions"]),6)
        self.assertEqual(len(self.seeds["route_groups"]),34)

    def test_versioned_asset_checksums(self):
        for asset in (self.seeds,self.template):
            payload={k:v for k,v in asset.items() if k!="content_sha256"}
            self.assertEqual(asset["content_sha256"],content_hash(payload))
        self.assertEqual(self.template["seed_content_sha256"],self.seeds["content_sha256"])

    def test_t02_destination_contract(self):
        fields = Destination.model_fields
        validated = DestinationDirectory(destinations=[{k:v for k,v in d.items() if k in fields} for d in self.seeds["destinations"]])
        self.assertEqual(len(validated.destinations),295)

    def test_all_relations_resolve(self):
        countries = {c["id"] for c in self.seeds["country_regions"]}
        regions = {r["id"] for r in self.seeds["regions"]}
        routes = {r["id"] for r in self.seeds["route_groups"]}
        self.assertTrue(all(d["country_region_id"] in countries and d["route_group_id"] in routes for d in self.seeds["destinations"]))
        self.assertTrue(all(r["region_id"] in regions for r in self.seeds["route_groups"]))

    def test_ids_stable_and_route_independent(self):
        for d in self.seeds["destinations"]:
            self.assertEqual(d["id"],uid("destination",d["canonical_key"]))

    def test_country_fields_never_suppressed_in_seed(self):
        self.assertTrue(all(c["name_en"] and c["name_zh"] for c in self.seeds["country_regions"]))
        self.assertTrue(all(d["display_name_en"] and d["display_name_zh"] for d in self.seeds["destinations"]))

    def test_no_price_records_in_public_seeds(self):
        forbidden = {"price_20gp","price_40gp","price_40hq","normalized_payload","raw_values","candidates"}
        def walk(obj):
            if isinstance(obj,dict):
                self.assertFalse(set(obj)&forbidden)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj,list):
                for v in obj:
                    walk(v)
        for obj in (self.seeds,self.template,self.diff,self.inventory):
            walk(obj)

    def test_sheet_order(self):
        self.assertEqual([s["name"] for s in self.template["sheets"]],load("config/quotation-columns-v1.json")["sheet_names"])

    def test_baseline_counts_per_sheet(self):
        self.assertEqual([len(s["baseline_layout"]["rows"]) for s in self.template["sheets"]],[69,61,27,68,49,21])

    def test_replay_generated_layout(self):
        for sheet in self.template["sheets"]:
            rows = [d for d in self.seeds["destinations"] if d["route_group_id"] in sheet["route_group_ids"]]
            self.assertEqual(plan_sheet(rows),sheet["baseline_layout"])

    def test_green_merge_and_freeze(self):
        self.assertEqual(self.template["freeze"],{"rows":2,"columns":5,"top_left_cell":"F3"})
        self.assertEqual(self.template["route_display"]["fill"],"#CFF2CF")
        for sheet in self.template["sheets"]:
            self.assertEqual(sheet["styles"]["route"]["fill"],"FFCFF2CF")
            self.assertTrue(sheet["baseline_layout"]["merges"][0]=="A1:R1")
            self.assertTrue(all(m.startswith("A") and ":A" in m for m in sheet["baseline_layout"]["merges"][1:]))

    def test_numeric_dates_and_month_day(self):
        self.assertEqual(self.template["value_policy"]["date_cell_type"],"EXCEL_SERIAL_NUMBER")
        self.assertEqual(self.template["value_policy"]["date_format"],"mm-dd")
        self.assertTrue(all(s["styles"]["date"]["number_format"]=="mm-dd" for s in self.template["sheets"]))

    def test_money_precision_and_no_change_highlight_in_base(self):
        self.assertEqual(self.template["value_policy"]["money_format"],"#,##0.####")
        self.assertTrue(all(s["styles"]["body"]["fill"]=="FFFFFFFF" for s in self.template["sheets"]))

    def test_version_count_conservation(self):
        n=self.diff["summary"]
        self.assertEqual(n["baseline_destination_rows"]-n["absent_baseline_keys"]+n["added_keys"],315)
        self.assertEqual(n["latest_distinct_keys"]+n["extra_quote_rows_same_destination"],316)
        self.assertEqual((n["common_keys"],n["added_keys"],n["absent_baseline_keys"]),(294,21,1))

    def test_no_baseline_destination_moved(self):
        self.assertEqual(self.diff["moved"],[])

    def test_alexandria_parent_not_deleted(self):
        r=self.diff["absent_from_v12"]
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["canonical_key"],"EGYPT|ALEXANDRIA")
        self.assertEqual(r[0]["decision"],"KEEP_PARENT_IDENTITY_NO_IMPLICIT_DELETE")
        self.assertEqual(len(self.diff["identity_decisions"][0]["child_keys"]),2)

    def test_labuan_multiple_quotes_one_destination(self):
        r=self.diff["duplicate_destination_rows"]
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["canonical_key"],"MALAYSIA|LABUAN")
        self.assertEqual(len(r[0]["rows"]),2)

    def test_added_routes_not_activated(self):
        self.assertEqual({r["name"] for r in self.diff["added_route_groups"]},{"黑海航线","文莱航线","柬埔寨航线"})
        self.assertTrue(all(r["status"]=="MIGRATION_PROPOSAL" for r in self.diff["added_route_groups"]))
        self.assertFalse(any(r["name"]=="黑海航线" for r in self.seeds["route_groups"]))

    def test_priced_rows_reconcile(self):
        self.assertEqual([s["priced_rows"] for s in self.inventory["sheets"]],[0,39,0,45,0,0])
        self.assertEqual(self.inventory["migration_quote_candidates"]+self.inventory["blank_placeholder_rows"],316)

    def test_destination_type_not_guessed_from_header(self):
        d={x["display_name_en"]:x for x in self.seeds["destinations"]}
        self.assertEqual(d["MEXICO CITY"]["kind"],"INLAND_POINT")
        self.assertEqual(d["TAN CANG QUE VO ICD"]["kind"],"ICD")
        self.assertEqual(d["HO CHI MINH (CAT LAI)"]["kind"],"UNKNOWN")


class LayoutTests(unittest.TestCase):
    def record(self,id,route="r1",country="c1"):
        return {"id":id,"route_group_id":route,"country_region_id":country}

    def test_empty_sheet_keeps_header_only(self):
        self.assertEqual(plan_sheet([])["merges"],["A1:R1"])
        self.assertEqual(plan_sheet([])["last_data_row"],2)

    def test_country_only_first_row_and_one_gap(self):
        result=plan_sheet([self.record("a"),self.record("b"),self.record("c",country="c2")])
        self.assertEqual([r["row"] for r in result["rows"]],[3,4,6])
        self.assertEqual([r["show_country"] for r in result["rows"]],[True,False,True])
        self.assertEqual(result["separator_rows"],[5])

    def test_route_switch_resets_country(self):
        result=plan_sheet([self.record("a"),self.record("b",route="r2")])
        self.assertEqual([r["row"] for r in result["rows"]],[3,5])
        self.assertEqual([r["show_country"] for r in result["rows"]],[True,True])

    def test_repeated_quote_destination_is_retained(self):
        result=plan_sheet([self.record("a"),self.record("a")])
        self.assertEqual(len(result["rows"]),2)

    def test_input_untouched(self):
        rows=[self.record("a"),self.record("b")]
        before=copy.deepcopy(rows)
        plan_sheet(rows)
        self.assertEqual(rows,before)

    def test_noncontiguous_route_rejected(self):
        with self.assertRaisesRegex(ValueError,"NONCONTIGUOUS_ROUTE"):
            plan_sheet([self.record("a"),self.record("b",route="r2"),self.record("c")])

    def test_noncontiguous_country_rejected(self):
        with self.assertRaisesRegex(ValueError,"NONCONTIGUOUS_COUNTRY"):
            plan_sheet([self.record("a"),self.record("b",country="c2"),self.record("c")])

    def test_conservative_name_normalization(self):
        self.assertEqual(normalize("  example   city  "),"EXAMPLE CITY")
        self.assertNotEqual(normalize("EXAMPLE (A)"),normalize("EXAMPLE (B)"))
        self.assertNotEqual(normalize("PORTLAND,OR"),normalize("PORTLAND"))


@unittest.skipUnless(V8.exists() and V12.exists(),"Private T01/T03 workbooks not available")
class PrivateReplayTests(unittest.TestCase):
    def test_all_generated_assets_reproducible(self):
        products,_=extract_assets()
        for path,data in products.items():
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),data,str(path.name))

    def test_source_hashes_match_locks(self):
        manifest=load("tests/fixtures/private/t03-v1/manifest.json")
        self.assertEqual(sha256(V12),manifest["sha256"])
        expected=next(s for s in load("tests/fixtures/private/t01-v1/manifest.json")["sources"] if s["source_id"]=="template-v8")
        self.assertEqual(sha256(V8),expected["sha256"])

    def test_exact_baseline_positions_and_merges(self):
        for sheet,configured in zip(read_book(V8)["sheets"],load("config/template-qingdao-v1.json")["sheets"]):
            self.assertEqual([r["row"] for r in sheet_rows(sheet)],[r["row"] for r in configured["baseline_layout"]["rows"]])
            self.assertEqual(sheet["merges"],configured["baseline_layout"]["merges"])

    def test_migration_quotes_are_candidates_only(self):
        cs=load("tests/fixtures/private/t03-v1/migration-candidates.json")["candidates"]
        self.assertEqual(len(cs),84)
        self.assertTrue(all(c["review_state"]=="PENDING_REVIEW" and c["application_state"]=="NOT_APPLIED" for c in cs))
        for c in cs:
            QuotationValues.model_validate(c["normalized_payload"])

    def test_validity_full_year_and_source_blank(self):
        for c in load("tests/fixtures/private/t03-v1/migration-candidates.json")["candidates"]:
            q=c["normalized_payload"]
            self.assertTrue(q["validity"]["valid_from"].startswith("2026-"))
            self.assertTrue(q["validity"]["valid_to"].startswith("2026-"))
            self.assertIsNone(q["source_code"])

    def test_original_three_amount_columns_preserved(self):
        cs=load("tests/fixtures/private/t03-v1/migration-candidates.json")["candidates"]
        for c in cs:
            for column,field in (("G","price_20gp"),("H","price_40gp"),("I","price_40hq")):
                self.assertEqual(c["raw_values"][column],c["normalized_payload"][field])

    def test_two_historical_date_periods(self):
        cs=load("tests/fixtures/private/t03-v1/migration-candidates.json")["candidates"]
        periods=Counter((c["normalized_payload"]["validity"]["valid_from"],c["normalized_payload"]["validity"]["valid_to"]) for c in cs)
        self.assertEqual(periods,{("2026-10-15","2026-10-31"):39,("2026-10-18","2026-10-24"):45})

    def test_original_working_v12_unchanged(self):
        original=ROOT/"outputs/qingdao-template-v1/青岛港海运报价表_v12_已添加地中海报价.xlsx"
        if not original.exists():
            self.skipTest("Optional original working file absent")
        self.assertEqual(sha256(original),sha256(V12))

    def test_private_prices_ignored_by_git(self):
        p=subprocess.run(["git","check-ignore","tests/fixtures/private/t03-v1/migration-candidates.json"],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


if __name__=="__main__":
    unittest.main()
