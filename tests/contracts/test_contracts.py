"""Synthetic contract tests: python -m unittest discover -s tests/contracts -v."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from backend.app.domain.contracts import (
    APIError, Candidate, CandidatePatch, ChangePlan, Condition, DestinationRef,
    DestinationDirectory, ErrorResponse, Evidence, ExportRequest, ExtractionOutput, ImageLocation,
    LocationCode, PatchRequest, PriceProfile, Provenance, QuotationValues,
    ReferencePrice, Routing, Schedule, UnassignedPair, Validity,
    derive_two_prices, edit_candidate, gate_issues, patch_proposal, payload_hash, scaled_money,
)

ROOT = Path(__file__).resolve().parents[2]
U1 = UUID("00000000-0000-4000-8000-000000000001")
U2 = UUID("00000000-0000-4000-8000-000000000002")
U3 = UUID("00000000-0000-4000-8000-000000000003")


def candidate(approved=False, **values):
    v = QuotationValues(origin_port_id=U1, destination_id=U2, price_20gp="123.45", **values)
    kwargs = dict(id=U3, batch_id=U1, raw_payload={}, normalized_payload=v,
                  field_provenance={}, issues=[], match_state="CONFIRMED")
    if approved:
        kwargs.update(review_state="APPROVED", review_version=1, reviewed_payload_hash=payload_hash(v),
                      reviewed_by=U1, reviewed_at="2026-10-17T09:00:00+08:00")
    return Candidate(**kwargs)


class MoneyTests(unittest.TestCase):
    def test_decimal_string_exact(self):
        self.assertEqual(scaled_money("123.4567"), 1234567)

    def test_zero_is_not_missing(self):
        self.assertEqual(QuotationValues(price_20gp="0").price_20gp, "0")
        self.assertIsNone(QuotationValues().price_20gp)

    def test_float_int_bool_not_accepted(self):
        for value in (1.1, 1, True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                QuotationValues(price_20gp=value)

    def test_bad_money(self):
        for value in ("", "--", "1e3", "NaN", "-1", "01", "1.12345", "100000000000000"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                QuotationValues(price_20gp=value)

    def test_wire_roundtrip(self):
        v = QuotationValues(price_20gp="12.3400")
        self.assertEqual(json.loads(v.model_dump_json())["price_20gp"], "12.3400")

    def test_two_price_rule_with_evidence(self):
        v, p = derive_two_prices("123", "234", confirmed_20gp_40ft=True, evidence_ids=[U1])
        self.assertEqual((v.price_40gp, v.price_40hq), ("234", "234"))
        self.assertEqual(p.rule_id, "TWO_PRICE_20GP_40FT_V1")

    def test_unlabelled_two_prices_blocked(self):
        for confirmed, evidence in ((False, [U1]), (True, [])):
            with self.assertRaises(ValueError):
                derive_two_prices("123", "234", confirmed_20gp_40ft=confirmed, evidence_ids=evidence)

    def test_hq_alone_does_not_fill_gp(self):
        self.assertIsNone(QuotationValues(price_40hq="234").price_40gp)


class DatePatchReviewTests(unittest.TestCase):
    def test_complete_cross_year(self):
        v = Validity(valid_from="2026-12-28", valid_to="2027-01-05")
        self.assertEqual(v.basis, "UNSPECIFIED")

    def test_date_input_rejections(self):
        for value in ("10-26", "2026-02-29", "2026-2-01", "2026-10-01T00:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Validity(valid_from=value)

    def test_reversed_date(self):
        with self.assertRaises(ValidationError):
            Validity(valid_from="2027-01-01", valid_to="2026-12-31")

    def test_etd_requires_explicit_selection(self):
        self.assertEqual(Validity(basis="ETD").basis, "ETD")
        self.assertEqual(Validity().basis, "UNSPECIFIED")

    def test_omission_vs_clear(self):
        old = QuotationValues(price_20gp="123", price_40gp="234")
        self.assertEqual(patch_proposal(old, CandidatePatch()).price_20gp, "123")
        changed = patch_proposal(old, CandidatePatch(price_20gp=None))
        self.assertIsNone(changed.price_20gp)
        self.assertEqual(changed.price_40gp, "234")

    def test_patch_zero(self):
        old = QuotationValues(price_20gp="123")
        self.assertEqual(patch_proposal(old, CandidatePatch(price_20gp="0")).price_20gp, "0")

    def test_structured_patch_replaces_whole_object(self):
        old = QuotationValues(validity=Validity(valid_from="2026-10-01", valid_to="2026-10-31"))
        new = patch_proposal(old, CandidatePatch(validity=Validity(valid_from="2026-11-01")))
        self.assertIsNone(new.validity.valid_to)
        with self.assertRaises(ValidationError):
            CandidatePatch(validity=None)

    def test_business_edit_invalidates_review(self):
        old = candidate(True)
        new = edit_candidate(old, PatchRequest(expected_version=1, changes=CandidatePatch(price_20gp="124")))
        self.assertEqual(new.version, 2)
        self.assertEqual(new.review_state, "PENDING_REVIEW")
        self.assertIsNone(new.reviewed_payload_hash)
        self.assertEqual(old.version, 1)

    def test_approval_hash_and_version(self):
        for changes in ({"review_version":2}, {"reviewed_payload_hash":"0"*64}, {"reviewed_by":None}):
            bad = candidate(True).model_dump(mode="json")
            bad.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Candidate.model_validate(bad)

    def test_noop_does_not_invalidate(self):
        c = candidate(True)
        self.assertIs(edit_candidate(c, PatchRequest(expected_version=1, changes=CandidatePatch())), c)

    def test_stale_edit_rejected(self):
        with self.assertRaisesRegex(ValueError, "VERSION_CONFLICT"):
            edit_candidate(candidate(), PatchRequest(expected_version=2, changes=CandidatePatch()))

    def test_destination_edit_requires_matching(self):
        c = edit_candidate(candidate(True), PatchRequest(expected_version=1, changes=CandidatePatch(destination_id=U3)))
        self.assertEqual(c.match_state, "UNMATCHED")

    def test_applied_candidate_immutable(self):
        c = candidate(True)
        c = Candidate.model_validate({**c.model_dump(mode="json"), "application_state":"APPLIED"})
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            edit_candidate(c, PatchRequest(expected_version=1, changes=CandidatePatch(price_20gp="200")))


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = json.loads((ROOT / "contracts/examples/extraction.synthetic.json").read_text(encoding="utf-8"))

    def test_synthetic_output(self):
        self.assertEqual(len(ExtractionOutput.model_validate(self.example).records[0].price_profiles), 4)

    def test_model_cannot_approve(self):
        bad = copy.deepcopy(self.example)
        bad["records"][0]["review_state"] = "APPROVED"
        with self.assertRaises(ValidationError):
            ExtractionOutput.model_validate(bad)

    def test_model_cannot_resolve_its_own_issue(self):
        bad = copy.deepcopy(self.example)
        bad["issues"] = [{"code":"CURRENCY_UNKNOWN", "message":"missing", "affected_actions":["COMPARE"],
                          "severity":"WARNING", "resolution":"RESOLVED"}]
        with self.assertRaises(ValidationError):
            ExtractionOutput.model_validate(bad)

    def test_dangling_group(self):
        bad = copy.deepcopy(self.example)
        bad["groups"] = [{"group_key":"g1", "label_raw":"group", "record_keys":["missing"], "evidence_ids":[]}]
        with self.assertRaisesRegex(ValidationError, "DANGLING_GROUP_RECORD"):
            ExtractionOutput.model_validate(bad)

    def test_condition_scope_is_checked(self):
        bad = copy.deepcopy(self.example)
        bad["conditions"][0]["scope"] = "GROUP"
        with self.assertRaisesRegex(ValidationError, "DANGLING_CONDITION_TARGET"):
            ExtractionOutput.model_validate(bad)

    def test_dangling_evidence(self):
        bad = copy.deepcopy(self.example)
        bad["evidence"] = []
        with self.assertRaisesRegex(ValidationError, "DANGLING_EVIDENCE"):
            ExtractionOutput.model_validate(bad)

    def test_duplicate_profile(self):
        bad = copy.deepcopy(self.example)
        bad["records"][0]["price_profiles"].append(bad["records"][0]["price_profiles"][0])
        with self.assertRaisesRegex(ValidationError, "DUPLICATE_PRICE_PROFILE"):
            ExtractionOutput.model_validate(bad)

    def test_reference_not_computed(self):
        p = ReferencePrice(kind="REFERENCE_PLUS_ADDON", raw_text="BASE+12", reference_raw="BASE", addon="12")
        self.assertIsNone(p.amount)
        with self.assertRaises(ValidationError):
            ReferencePrice(**{**p.model_dump(), "amount":"112"})

    def test_pair_has_no_container_assignment(self):
        p = UnassignedPair(kind="PAIR_UNASSIGNED", raw_text="12/34", tokens=["12", "34"])
        self.assertIsNone(p.amount)

    def test_yellow_columns_not_automatically_bound(self):
        p = self.example["records"][0]["price_profiles"][1]
        p = {**p, "container_map":{"g1":"20GP"}}
        with self.assertRaisesRegex(ValidationError, "UNCONFIRMED_CONTAINER_MAPPING"):
            PriceProfile.model_validate(p)

    def test_transit_options_not_range(self):
        s = Schedule(transit_days_raw="2/4", transit_day_options=[2,4], transit_binding="ALTERNATIVES")
        self.assertEqual(s.transit_binding, "ALTERNATIVES")
        self.assertIsNone(QuotationValues(schedule=s).currency)

    def test_weekday_limits(self):
        for value in (0,8,True):
            with self.assertRaises(ValidationError):
                Schedule(weekdays=[value])

    def test_invalid_bbox(self):
        for bbox in ((0.5,0,0.1,1), (0,0,2,1)):
            with self.assertRaises(ValidationError):
                ImageLocation(kind="IMAGE_REGION", bbox=bbox)

    def test_derivation_requires_rule(self):
        with self.assertRaisesRegex(ValidationError, "DERIVATION_RULE_REQUIRED"):
            Provenance(raw_value="1", normalized_value="1", origin="RULE_DERIVED", evidence_ids=[U1])

    def test_source_code_namespace(self):
        with self.assertRaisesRegex(ValidationError, "SOURCE_NAMESPACE_REQUIRED"):
            LocationCode(namespace="SOURCE_SPECIFIC", value="X")

    def test_terminal_identity_retained(self):
        a = DestinationRef(kind="TERMINAL", name_en="EXAMPLE CITY", terminal_name="TERMINAL A", destination_id=U1)
        b = DestinationRef(kind="TERMINAL", name_en="EXAMPLE CITY", terminal_name="TERMINAL B", destination_id=U2)
        self.assertNotEqual(a.destination_id, b.destination_id)
        self.assertIsNone(DestinationRef(name_en="EXAMPLE CITY").destination_id)

    def test_unknown_routing_is_not_direct(self):
        self.assertEqual(Routing().status, "UNKNOWN")
        with self.assertRaises(ValidationError):
            Routing(status="DIRECT")

    def test_direct_and_transit(self):
        p = Routing(status="TRANSSHIPMENT", nodes=[{"name_en":x} for x in ("POL", "HUB", "POD")])
        self.assertEqual(" → ".join(n.name_en for n in p.nodes), "POL → HUB → POD")


class GatesAndGeneratedTests(unittest.TestCase):
    def test_unknown_currency_does_not_block_internal_apply(self):
        issues = gate_issues(candidate(True), qingdao_origin_id=U1)
        self.assertEqual([i.code for i in issues], ["CURRENCY_UNKNOWN"])
        self.assertEqual(issues[0].affected_actions, ["COMPARE"])

    def test_missing_origin_blocks(self):
        c = candidate(True)
        v = c.normalized_payload.model_dump(mode="json")
        v["origin_port_id"] = None
        c = candidate()
        c = Candidate.model_validate({**c.model_dump(mode="json"), "normalized_payload":v})
        self.assertIn("ORIGIN_NOT_CONFIRMED_QINGDAO", [i.code for i in gate_issues(c, qingdao_origin_id=U1)])

    def test_source_code_not_carrier(self):
        self.assertIsNone(candidate().normalized_payload.source_code)

    def test_review_timestamp_requires_timezone(self):
        bad = candidate(True).model_dump(mode="json")
        bad["reviewed_at"] = "2026-10-17T09:00:00"
        with self.assertRaises(ValidationError):
            Candidate.model_validate(bad)

    def test_one_destination_one_route_assignment(self):
        d = {"id":str(U1),"canonical_key":"EXAMPLE:A","country_region_id":str(U2),"kind":"SEAPORT",
             "display_name_en":"EXAMPLE", "display_name_zh":"示例港", "route_group_id":str(U2)}
        other = {**d, "route_group_id":str(U3)}
        with self.assertRaisesRegex(ValidationError, "DESTINATION_DUPLICATE_ASSIGNMENT"):
            DestinationDirectory(destinations=[d, other])

    def test_error_envelope(self):
        e = ErrorResponse(error=APIError(code="PLAN_STALE", message="预览已过期", request_id="synthetic"))
        self.assertEqual(json.loads(e.model_dump_json())["error"]["code"], "PLAN_STALE")

    def test_versions_strict(self):
        with self.assertRaises(ValidationError):
            PatchRequest(expected_version=True, changes=CandidatePatch())

    def test_changes_only_export_not_allowed(self):
        with self.assertRaises(ValidationError):
            ExportRequest(mode="CHANGES_ONLY", dataset_version=1)

    def test_columns(self):
        c = json.loads((ROOT / "config/quotation-columns-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(c["sheet_names"]), 6)
        self.assertEqual([x["letter"] for x in c["columns"]], list("ABCDEFGHIJKLMNOPQR"))
        self.assertEqual(len({x["field"] for x in c["columns"]}), 18)
        self.assertEqual(c["date_display"], "mm-dd")

    def test_generated_artifacts_have_no_drift(self):
        spec = importlib.util.spec_from_file_location("generate", ROOT / "contracts/generate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, data in module.build().items():
            actual = (ROOT / name).read_text(encoding="utf-8")
            expected = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            with self.subTest(name=name):
                self.assertEqual(actual, expected)

    def test_openapi_refs_resolve(self):
        api = json.loads((ROOT / "contracts/openapi.json").read_text(encoding="utf-8"))
        def walk(obj):
            if isinstance(obj, dict):
                if "$ref" in obj:
                    node = api
                    for key in obj["$ref"].removeprefix("#/").split("/"):
                        node = node[key]
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
        walk(api)


if __name__ == "__main__":
    unittest.main()
