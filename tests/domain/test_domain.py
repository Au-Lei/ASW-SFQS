"""T06 business invariants using synthetic amounts and destinations only."""
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
from uuid import UUID

from pydantic import ValidationError
from backend.app.domain import candidates as commands
from backend.app.domain.contracts import (
    ApplicationState, Candidate, CandidatePatch, ContainerType, Destination,
    Evidence, ExtractionOutput, Issue, MatchState, PatchRequest, PlanState, Provenance,
    QuotationValues, ReviewRequest, ReviewState, Schedule, Validity,
    derive_two_prices, payload_hash, scaled_money,
)
from backend.app.domain.errors import DomainError
from backend.app.domain.transitions import require_transition
from backend.app.domain.validation import (
    EvidenceContext, action_blockers, candidate_issues, provenance_issues,
    require_action, same_value,
)
from backend.app.domain.values import (
    DateApplicability, DateWindow, MoneyAmount, confirmed_month_day, full_date,
    price_for_container,
)
from backend.app.repositories.types import Money as StoredMoney


ORIGIN, DEST, ACTOR, EVIDENCE_ID, FILE_ID, BATCH, CANDIDATE = [UUID(int=i) for i in range(1, 8)]
NOW = datetime(2026, 10, 17, 9, tzinfo=timezone.utc)


def candidate(**updates):
    values = QuotationValues(origin_port_id=ORIGIN, destination_id=DEST, price_20gp="12.3400",
        currency="USD", price_scope_summary="synthetic base ocean freight",
        validity=Validity(valid_from="2026-12-28", valid_to="2027-01-05", basis="ETD"))
    fields = {key: Provenance(raw_value=value, normalized_value=value, origin="MANUAL",
        recorded_by=ACTOR, recorded_at=NOW.isoformat()) for key, value in values.model_dump(mode="json").items()
        if value != QuotationValues().model_dump(mode="json")[key]}
    data = dict(id=CANDIDATE, batch_id=BATCH, normalized_payload=values,
                raw_payload={"source": "synthetic source"}, field_provenance=fields,
                issues=[], match_state="CONFIRMED")
    data.update(updates)
    return Candidate(**data)


def review(current, decision="APPROVED", acknowledgments=()):
    return commands.review_candidate(current, ReviewRequest(expected_version=current.version,
        payload_hash=payload_hash(current.normalized_payload), decision=decision,
        acknowledged_issue_codes=list(acknowledgments)), actor_id=ACTOR,
        qingdao_origin_id=ORIGIN, at=NOW)


def edited(current, **changes):
    return commands.edit_candidate(current, PatchRequest(expected_version=current.version,
        changes=CandidatePatch(**changes)), actor_id=ACTOR, at=NOW)


def with_values(current, **changes):
    values = current.normalized_payload.model_dump(mode="json")
    values.update(changes)
    # Rebuild the fixture, explicitly confirming the synthetic values.
    v = QuotationValues.model_validate(values)
    base = candidate()
    data = base.model_dump(mode="json")
    data["normalized_payload"] = v.model_dump(mode="json")
    data["field_provenance"] = {key: Provenance(raw_value=value, normalized_value=value,
        origin="MANUAL", recorded_by=ACTOR, recorded_at=NOW.isoformat()).model_dump(mode="json")
        for key, value in data["normalized_payload"].items()
        if value != QuotationValues().model_dump(mode="json")[key]}
    return Candidate.model_validate(data)


class MoneyAndContainerTests(unittest.TestCase):
    def test_decimal_context_cannot_round_scaling_or_db_reads(self):
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(scaled_money("12345678901234.5678"), 123456789012345678)
            self.assertEqual(MoneyAmount("12345678901234.5678").decimal, Decimal("12345678901234.5678"))
            self.assertEqual(StoredMoney().process_result_value(123456789012345678, None), Decimal("12345678901234.5678"))

    def test_money_equality_and_wire_are_exact(self):
        self.assertEqual(MoneyAmount("12.3400"), MoneyAmount(Decimal("12.34")))
        self.assertEqual(MoneyAmount("0.0001").scaled, 1)
        self.assertEqual(MoneyAmount.from_scaled(1).wire, "0.0001")
        self.assertEqual(MoneyAmount("0.0000").wire, "0")
        self.assertEqual(MoneyAmount("100.0000").wire, "100")
        self.assertEqual(MoneyAmount.from_scaled(999999999999999999).wire, "99999999999999.9999")

    def test_money_rejects_rounding_and_coercion(self):
        for value in (True, 1, 1.25, "1e2", "-0", "-1", "01", "0.00001", "100000000000000", Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises((ValidationError, ValueError)):
                MoneyAmount(value)

    def test_scaled_requires_bounded_integer(self):
        for value in (True, 1.0, -1, 1000000000000000000):
            with self.subTest(value=value), self.assertRaises(DomainError):
                MoneyAmount.from_scaled(value)

    def test_money_is_immutable(self):
        value = MoneyAmount("1")
        with self.assertRaises(FrozenInstanceError):
            value.scaled = 2

    def test_selected_container_never_falls_back(self):
        values = QuotationValues(price_20gp="0", price_40hq="25")
        self.assertEqual(price_for_container(values, ContainerType.GP20).scaled, 0)
        self.assertIsNone(price_for_container(values, "40GP"))
        self.assertEqual(price_for_container(values, "40HQ").wire, "25")
        for value in ("40FT", "40HC", "20", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                price_for_container(values, value)

    def test_two_price_requires_actual_boolean_and_evidence(self):
        for value in (1, "yes", False, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                derive_two_prices("12", "24", confirmed_20gp_40ft=value, evidence_ids=[EVIDENCE_ID])
        values, proof = derive_two_prices("0", "24.0001", confirmed_20gp_40ft=True, evidence_ids=[EVIDENCE_ID])
        self.assertEqual(values.price_20gp, "0")
        self.assertEqual(values.price_40gp, values.price_40hq)
        self.assertEqual(proof.origin, "RULE_DERIVED")


class DateScheduleTests(unittest.TestCase):
    def test_cross_year_inclusive_and_outside(self):
        window = DateWindow.from_validity(Validity(valid_from="2026-12-28", valid_to="2027-01-05", basis="ETD"))
        for day in ("2026-12-28", "2027-01-01", "2027-01-05"):
            self.assertEqual(window.assess(day, basis="ETD"), DateApplicability.MATCH)
        for day in ("2026-12-27", "2027-01-06"):
            self.assertEqual(window.assess(day, basis="ETD"), DateApplicability.OUTSIDE)

    def test_unknown_or_different_basis_never_claims_etd_validity(self):
        for basis in ("UNSPECIFIED", "BOOKING_DATE"):
            window = DateWindow(date(2026, 1, 1), date(2026, 1, 2), basis)
            self.assertEqual(window.assess("2026-02-01", basis="ETD"), DateApplicability.UNCONFIRMED)
        self.assertEqual(DateWindow(date(2026, 1, 1), date(2026, 1, 2), "ETD").assess("2026-01-01", basis="UNSPECIFIED"), DateApplicability.UNCONFIRMED)

    def test_unknown_bounds_are_not_fabricated(self):
        self.assertEqual(DateWindow(None, None, "ETD").assess("2026-01-01", basis="ETD"), DateApplicability.UNCONFIRMED)
        window = DateWindow(date(2026, 1, 2), None, "ETD")
        self.assertEqual(window.assess("2026-01-01", basis="ETD"), DateApplicability.OUTSIDE)
        self.assertEqual(window.assess("2026-01-03", basis="ETD"), DateApplicability.UNCONFIRMED)

    def test_month_day_requires_confirmed_year(self):
        for year in (None, True, 0):
            with self.assertRaises(DomainError):
                confirmed_month_day("01-05", year=year)
        self.assertEqual(confirmed_month_day("02-29", year=2028), date(2028, 2, 29))
        with self.assertRaises(ValueError):
            confirmed_month_day("02-29", year=2026)

    def test_complete_dates_reject_timestamps_and_bad_calendar(self):
        for value in ("10-01", "2026-2-01", "2026-02-30", "0000-01-01", datetime(2026, 1, 1)):
            with self.subTest(value=value), self.assertRaises((ValueError, ValidationError)):
                full_date(value)
        with self.assertRaises(DomainError):
            DateWindow(date(2027, 1, 1), date(2026, 1, 1))

    def test_schedule_normalizes_weekdays_without_creating_an_etd(self):
        schedule = Schedule(weekdays=[7, 1, 7, 3])
        self.assertEqual(schedule.weekdays, [1, 3, 7])
        self.assertNotIn("etd", schedule.model_dump())
        for value in (0, 8, True, "1"):
            with self.assertRaises(ValidationError):
                Schedule(weekdays=[value])

    def test_alternatives_are_not_a_range(self):
        schedule = Schedule(transit_day_options=[17, 11], transit_binding="ALTERNATIVES")
        self.assertEqual(schedule.transit_day_options, [17, 11])
        for values, binding in (([], "SINGLE"), ([1, 2], "SINGLE"), ([2], "ALTERNATIVES"), ([2, 2], "ALTERNATIVES"), ([17, 11], "CONFIRMED_RANGE")):
            with self.subTest(values=values, binding=binding), self.assertRaises(ValidationError):
                Schedule(transit_day_options=values, transit_binding=binding)


class ProvenanceAndGateTests(unittest.TestCase):
    def test_model_cannot_claim_human_confirmation(self):
        root = Path(__file__).resolve().parents[2]
        output = json.loads((root / "contracts/examples/extraction.synthetic.json").read_text(encoding="utf-8"))
        output["records"][0]["field_provenance"] = {"price_20gp": {
            "raw_value":"12", "normalized_value":"12", "origin":"MANUAL",
            "recorded_by":str(ACTOR), "recorded_at":NOW.isoformat()}}
        with self.assertRaisesRegex(ValidationError, "MODEL_CANNOT_CLAIM_HUMAN_PROVENANCE"):
            ExtractionOutput.model_validate(output)

    def test_year_and_condition_references_cannot_be_orphans(self):
        current = with_values(candidate(), validity=Validity(valid_from="2026-12-28", valid_to="2027-01-05", basis="ETD", year_evidence_ids=[EVIDENCE_ID]).model_dump(mode="json"), condition_keys=["synthetic-condition"])
        errors = {i.code for i in provenance_issues(current)}
        self.assertIn("EVIDENCE_CONTEXT_REQUIRED", errors)
        self.assertIn("CONDITION_CONTEXT_REQUIRED", errors)
        errors = {i.code for i in provenance_issues(current, context=EvidenceContext())}
        self.assertIn("EVIDENCE_NOT_FOUND", errors)
        self.assertIn("CONDITION_NOT_FOUND", errors)
        evidence = Evidence(id=EVIDENCE_ID, file_id=FILE_ID, original_text="2026", location={"kind":"XLSX_CELL", "sheet_name":"test", "cell_range":"A1"})
        context = EvidenceContext({EVIDENCE_ID:evidence}, frozenset({FILE_ID}), frozenset({"synthetic-condition"}))
        self.assertEqual(provenance_issues(current, context=context), [])

    def test_derived_hq_rechecks_inputs_after_gp_is_edited(self):
        values, derived = derive_two_prices("12", "24", confirmed_20gp_40ft=True, evidence_ids=[EVIDENCE_ID])
        current = with_values(candidate(), price_20gp=values.price_20gp, price_40gp=values.price_40gp, price_40hq=values.price_40hq)
        current.field_provenance["price_40hq"] = derived
        evidence = Evidence(id=EVIDENCE_ID, file_id=FILE_ID, original_text="20GP/40FT", location={"kind":"XLSX_CELL", "sheet_name":"test", "cell_range":"A1"})
        context = EvidenceContext({EVIDENCE_ID:evidence}, frozenset({FILE_ID}))
        self.assertEqual(provenance_issues(current, context=context), [])
        changed = edited(current, price_40gp="25").candidate
        self.assertIn("TWO_PRICE_DERIVATION_STALE", {i.code for i in provenance_issues(changed, context=context)})
        self.assertEqual(changed.normalized_payload.price_40hq, "24")

    def test_fabricated_derivation_rule_is_not_a_confirmed_value(self):
        current = candidate()
        current.field_provenance["price_20gp"] = Provenance(raw_value="12.3400", normalized_value="12.3400", origin="RULE_DERIVED", rule_id="MODEL_GUESSED_RULE", evidence_ids=[EVIDENCE_ID])
        self.assertIn("DERIVATION_RULE_UNKNOWN", {i.code for i in provenance_issues(current)})

    def test_blank_nullable_fields_are_not_unknown_codes(self):
        for key in ("source_code", "service_name", "price_profile_key", "remarks", "price_scope_summary"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                QuotationValues(**{key:"  "})

    def test_draft_candidates_cannot_be_exported_as_a_formal_workbook(self):
        approved = review(candidate()).candidate
        self.assertIn("FORMAL_EXPORT_REQUIRES_SNAPSHOT", {i.code for i in action_blockers(approved, "EXPORT", qingdao_origin_id=ORIGIN)})

    def test_explicit_proof_requires_real_in_batch_evidence(self):
        current = candidate()
        current.field_provenance["price_20gp"] = Provenance(raw_value="12.3400", normalized_value="12.3400", origin="EXPLICIT", evidence_ids=[EVIDENCE_ID])
        self.assertIn("EVIDENCE_CONTEXT_REQUIRED", {i.code for i in provenance_issues(current)})
        self.assertIn("EVIDENCE_NOT_FOUND", {i.code for i in provenance_issues(current, context=EvidenceContext())})
        evidence = Evidence(id=EVIDENCE_ID, file_id=FILE_ID, original_text="12.3400", location={"kind":"XLSX_CELL", "sheet_name":"test", "cell_range":"A1"})
        context = EvidenceContext({EVIDENCE_ID:evidence}, frozenset())
        self.assertIn("EVIDENCE_OUTSIDE_BATCH", {i.code for i in provenance_issues(current, context=context)})
        context = EvidenceContext({EVIDENCE_ID:evidence}, frozenset({FILE_ID}))
        self.assertEqual(provenance_issues(current, context=context), [])

    def test_manual_fields_require_actor_and_time(self):
        with self.assertRaises(ValidationError):
            Provenance(raw_value="12", normalized_value="12", origin="MANUAL")
        with self.assertRaises(ValidationError):
            Provenance(raw_value="12", normalized_value="12", origin="MANUAL", recorded_by=ACTOR, recorded_at="2026-10-17T09:00:00")

    def test_missing_and_mismatching_proof_block_review(self):
        current = candidate(field_provenance={})
        self.assertIn("PROVENANCE_MISSING", {i.code for i in action_blockers(current, "REVIEW", qingdao_origin_id=ORIGIN)})
        current = candidate()
        current.field_provenance["price_20gp"].normalized_value = "99"
        self.assertIn("PROVENANCE_VALUE_MISMATCH", {i.code for i in provenance_issues(current)})

    def test_types_are_not_equal_by_numeric_coercion(self):
        self.assertFalse(same_value([1], [True]))
        self.assertFalse(same_value([1], [1.0]))
        self.assertTrue(same_value({"a":1, "b":2}, {"b":2, "a":1}))

    def test_unknown_provenance_for_null_does_not_block_known_missing(self):
        current = with_values(candidate(), currency=None)
        current.field_provenance["currency"] = Provenance(raw_value=None, normalized_value=None, origin="UNKNOWN")
        self.assertEqual(action_blockers(current, "REVIEW", qingdao_origin_id=ORIGIN), [])
        self.assertIn("CURRENCY_UNKNOWN", {i.code for i in candidate_issues(current, qingdao_origin_id=ORIGIN)})

    def test_unknown_nonempty_proof_does_block_review(self):
        current = candidate()
        current.field_provenance["price_20gp"] = Provenance(raw_value="12", normalized_value="12.3400", origin="UNKNOWN", confidence=1)
        self.assertIn("PROVENANCE_UNCONFIRMED", {i.code for i in action_blockers(current, "REVIEW", qingdao_origin_id=ORIGIN)})

    def test_unknown_source_and_carrier_do_not_block_apply(self):
        approved = review(candidate()).candidate
        self.assertEqual(action_blockers(approved, "APPLY", qingdao_origin_id=ORIGIN), [])
        self.assertIsNone(approved.normalized_payload.carrier_id)
        self.assertIsNone(approved.normalized_payload.source_code)

    def test_currency_unknown_can_be_approved_without_inventing_usd(self):
        current = with_values(candidate(), currency=None)
        approved = review(current, acknowledgments=("CURRENCY_UNKNOWN",)).candidate
        self.assertIsNone(approved.normalized_payload.currency)
        self.assertEqual(action_blockers(approved, "APPLY", qingdao_origin_id=ORIGIN), [])
        self.assertIn("CURRENCY_UNKNOWN", {i.code for i in action_blockers(approved, "COMPARE", qingdao_origin_id=ORIGIN)})

    def test_missing_dates_affect_dates_not_internal_save(self):
        current = with_values(candidate(), validity=Validity().model_dump(mode="json"))
        approved = review(current, acknowledgments=("VALIDITY_INCOMPLETE", "VALIDITY_BASIS_UNSPECIFIED")).candidate
        self.assertEqual(action_blockers(approved, "APPLY", qingdao_origin_id=ORIGIN), [])
        self.assertEqual(len(action_blockers(approved, "DATE_FILTER", qingdao_origin_id=ORIGIN)), 2)

    def test_selected_container_missing_never_becomes_zero(self):
        approved = review(candidate()).candidate
        issues = action_blockers(approved, "COMPARE", qingdao_origin_id=ORIGIN, container="40GP")
        self.assertIn("CONTAINER_PRICE_MISSING", {i.code for i in issues})
        self.assertIsNone(approved.normalized_payload.price_40gp)
        self.assertEqual(action_blockers(approved, "COMPARE", qingdao_origin_id=ORIGIN, container="20GP"), [])

    def test_no_literal_price_can_be_reviewed_but_not_applied(self):
        current = with_values(candidate(), price_20gp=None)
        approved = review(current, acknowledgments=("NO_LITERAL_PRICE",)).candidate
        self.assertIn("NO_LITERAL_PRICE", {i.code for i in action_blockers(approved, "APPLY", qingdao_origin_id=ORIGIN)})

    def test_unmatched_price_can_be_reviewed_but_not_applied(self):
        current = candidate(match_state="UNMATCHED")
        approved = review(current, acknowledgments=("DESTINATION_NOT_CONFIRMED",)).candidate
        self.assertEqual(approved.review_state, "APPROVED")
        self.assertIn("DESTINATION_NOT_CONFIRMED", {i.code for i in action_blockers(approved, "APPLY", qingdao_origin_id=ORIGIN)})

    def test_resolving_a_missing_currency_issue_cannot_bypass_recheck(self):
        current = with_values(candidate(), currency=None)
        current.issues = [Issue(code="CURRENCY_UNKNOWN", field_paths=["currency"], message="test", affected_actions=["COMPARE"], severity="WARNING", resolution="RESOLVED", acknowledged_by=ACTOR, acknowledged_at=NOW.isoformat())]
        self.assertIn("CURRENCY_UNKNOWN", {i.code for i in action_blockers(current, "COMPARE", qingdao_origin_id=ORIGIN)})

    def test_review_specific_issue_stays_blocking_after_acknowledgment(self):
        current = candidate(issues=[Issue(code="TERMINAL_AMBIGUOUS", field_paths=["destination_id"], message="test", affected_actions=["REVIEW", "APPLY"], severity="WARNING", resolution="ACKNOWLEDGED", acknowledged_by=ACTOR, acknowledged_at=NOW.isoformat())])
        with self.assertRaisesRegex(DomainError, "ACTION_BLOCKED"):
            review(current)

    def test_issue_ack_requires_actor(self):
        with self.assertRaises(ValidationError):
            Issue(code="TEST", message="test", affected_actions=[], severity="INFO", resolution="RESOLVED")

    def test_unknown_currency_fee_scope_and_date_are_independent(self):
        current = with_values(candidate(), currency=None, price_scope_summary=None, validity=Validity().model_dump(mode="json"))
        self.assertEqual(action_blockers(current, "REVIEW", qingdao_origin_id=ORIGIN), [])
        approved = review(current, acknowledgments=("CURRENCY_UNKNOWN", "PRICE_SCOPE_UNKNOWN", "VALIDITY_INCOMPLETE", "VALIDITY_BASIS_UNSPECIFIED")).candidate
        self.assertEqual({i.code for i in action_blockers(approved, "COMPARE", qingdao_origin_id=ORIGIN)}, {"CURRENCY_UNKNOWN", "PRICE_SCOPE_UNKNOWN"})
        with self.assertRaises(DomainError) as error:
            require_action(current, "DATE_FILTER", qingdao_origin_id=ORIGIN)
        self.assertEqual(error.exception.code, "ACTION_BLOCKED")


class CandidateCommandTests(unittest.TestCase):
    def test_fixed_missing_value_retires_old_warning_after_reapproval(self):
        current = with_values(candidate(), currency=None)
        approved = review(current, acknowledgments=("CURRENCY_UNKNOWN",)).candidate
        corrected = edited(approved, currency="USD").candidate
        result = review(corrected).candidate
        self.assertEqual(action_blockers(result, "COMPARE", qingdao_origin_id=ORIGIN, container="20GP"), [])
        self.assertNotIn("CURRENCY_UNKNOWN", {item.code for item in result.issues})

    def test_old_acknowledgment_is_not_reused_after_business_edit(self):
        current = with_values(candidate(), currency=None)
        approved = review(current, acknowledgments=("CURRENCY_UNKNOWN",)).candidate
        changed = edited(approved, price_20gp="13").candidate
        with self.assertRaisesRegex(DomainError, "ACKNOWLEDGMENT_REQUIRED"):
            review(changed)

    def test_approval_binds_hash_version_human_and_is_not_application(self):
        current = candidate()
        result = review(current)
        approved = result.candidate
        self.assertEqual(approved.version, 2)
        self.assertEqual(approved.review_version, 2)
        self.assertEqual(approved.reviewed_payload_hash, payload_hash(current.normalized_payload))
        self.assertEqual(approved.reviewed_by, ACTOR)
        self.assertEqual(approved.application_state, "NOT_APPLIED")
        self.assertEqual(current.review_state, "PENDING_REVIEW")
        self.assertEqual(result.event.action, "REVIEW_CANDIDATE")

    def test_business_edit_clears_all_approval_fields_and_tracks_human(self):
        approved = review(candidate()).candidate
        result = edited(approved, price_20gp="0")
        current = result.candidate
        self.assertEqual(current.version, 3)
        self.assertEqual(current.review_state, "PENDING_REVIEW")
        for name in ("review_version", "reviewed_payload_hash", "reviewed_by", "reviewed_at"):
            self.assertIsNone(getattr(current, name))
        proof = current.field_provenance["price_20gp"]
        self.assertEqual(proof.origin, "MANUAL")
        self.assertEqual(proof.recorded_by, ACTOR)
        self.assertEqual(proof.normalized_value, "0")
        self.assertEqual(current.raw_payload, approved.raw_payload)
        self.assertEqual(json.loads(result.event.before_json)["review_state"], "APPROVED")
        self.assertNotEqual(result.event.before_hash, result.event.after_hash)

    def test_omission_clear_and_noop_have_distinct_behavior(self):
        approved = review(candidate()).candidate
        self.assertIsNone(edited(approved).event)
        self.assertEqual(edited(approved).candidate.version, approved.version)
        changed = edited(approved, price_20gp=None).candidate
        self.assertIsNone(changed.normalized_payload.price_20gp)
        self.assertEqual(changed.field_provenance["price_20gp"].normalized_value, None)
        self.assertEqual(changed.review_state, "PENDING_REVIEW")

    def test_structured_replacement_keeps_old_raw_in_event(self):
        approved = review(candidate()).candidate
        result = edited(approved, validity=Validity(valid_from="2027-02-01"))
        self.assertIsNone(result.candidate.normalized_payload.validity.valid_to)
        self.assertEqual(result.candidate.field_provenance["validity"].normalized_value["valid_from"], "2027-02-01")
        self.assertEqual(json.loads(result.event.before_json)["normalized_payload"]["validity"]["valid_to"], "2027-01-05")

    def test_identity_context_edits_require_rematching(self):
        for changes in ({"destination_id":ACTOR}, {"origin_port_id":ACTOR}, {"source_id":ACTOR}):
            with self.subTest(changes=changes):
                result = edited(review(candidate()).candidate, **changes)
                self.assertEqual(result.candidate.match_state, "UNMATCHED")

    def test_pending_info_and_rejection_require_reopen(self):
        for state in ("NEEDS_INFO", "REJECTED"):
            current = review(candidate(), state).candidate
            with self.assertRaisesRegex(DomainError, "STATE_TRANSITION_FORBIDDEN"):
                review(current)
            reopened = review(current, "PENDING_REVIEW").candidate
            self.assertEqual(review(reopened).candidate.review_state, "APPROVED")

    def test_stale_request_and_changed_snapshot_refused(self):
        current = candidate()
        request = ReviewRequest(expected_version=2, payload_hash=payload_hash(current.normalized_payload), decision="APPROVED")
        with self.assertRaisesRegex(DomainError, "VERSION_CONFLICT"):
            commands.review_candidate(current, request, actor_id=ACTOR, qingdao_origin_id=ORIGIN)
        request = ReviewRequest(expected_version=1, payload_hash="0"*64, decision="APPROVED")
        with self.assertRaisesRegex(DomainError, "REVIEW_PAYLOAD_CHANGED"):
            commands.review_candidate(current, request, actor_id=ACTOR, qingdao_origin_id=ORIGIN)

    def test_all_applied_outcomes_are_immutable(self):
        for outcome in ("APPLIED", "NO_CHANGE", "EXCLUDED"):
            current = review(candidate()).candidate
            current.application_state = ApplicationState(outcome)
            with self.subTest(outcome=outcome), self.assertRaisesRegex(DomainError, "IMMUTABLE"):
                edited(current, price_20gp="13")
            with self.assertRaisesRegex(DomainError, "IMMUTABLE"):
                review(current, "PENDING_REVIEW")

    def test_missing_information_requires_explicit_acknowledgment(self):
        current = with_values(candidate(), currency=None)
        with self.assertRaises(DomainError) as error:
            review(current)
        self.assertEqual(error.exception.code, "ACKNOWLEDGMENT_REQUIRED")
        self.assertIn("CURRENCY_UNKNOWN", error.exception.issue_codes)
        with self.assertRaisesRegex(DomainError, "ACKNOWLEDGMENT_UNKNOWN"):
            review(current, acknowledgments=("CURRENCY_UNKNOWN", "MADE_UP"))

    def test_manual_confirmation_of_missing_proof_is_a_new_review_version(self):
        current = candidate(field_provenance={})
        with self.assertRaisesRegex(DomainError, "ACTION_BLOCKED"):
            review(current)
        result = commands.confirm_fields(current, {"origin_port_id", "destination_id", "price_20gp", "currency", "validity", "price_scope_summary"}, expected_version=1, actor_id=ACTOR, at=NOW)
        self.assertEqual(review(result.candidate).candidate.review_state, "APPROVED")
        with self.assertRaisesRegex(DomainError, "PROVENANCE_OVERLAPPING_FIELDS"):
            commands.confirm_fields(current, {"validity", "validity.valid_from"}, expected_version=1, actor_id=ACTOR)

    def test_proof_only_change_invalidates_approval(self):
        current = review(candidate()).candidate
        proof = Provenance(raw_value="12.3400", normalized_value="12.3400", origin="EXPLICIT", evidence_ids=[EVIDENCE_ID])
        evidence = Evidence(id=EVIDENCE_ID, file_id=FILE_ID, original_text="12.3400", location={"kind":"XLSX_CELL", "sheet_name":"test", "cell_range":"G2"})
        result = commands.replace_provenance(current, {"price_20gp":proof}, expected_version=2, actor_id=ACTOR, context=EvidenceContext({EVIDENCE_ID:evidence}, frozenset({FILE_ID})), at=NOW)
        self.assertEqual(result.candidate.review_state, "PENDING_REVIEW")
        self.assertEqual(result.candidate.normalized_payload, current.normalized_payload)
        self.assertEqual(result.candidate.version, 3)
        self.assertIsNone(result.candidate.reviewed_payload_hash)

    def test_matching_requires_active_directory_identity_and_invalidates_review(self):
        current = candidate(match_state="UNMATCHED")
        destination = Destination(id=DEST, canonical_key="test:dest", country_region_id=ACTOR, kind="SEAPORT", display_name_en="TEST", display_name_zh="测试港", route_group_id=ACTOR)
        result = commands.match_candidate(current, "CONFIRMED", expected_version=1, actor_id=ACTOR, destination=destination, at=NOW)
        self.assertEqual(result.candidate.match_state, "CONFIRMED")
        self.assertEqual(result.candidate.review_state, "PENDING_REVIEW")
        with self.assertRaisesRegex(DomainError, "DESTINATION_INACTIVE"):
            commands.match_candidate(current, "CONFIRMED", expected_version=1, actor_id=ACTOR, destination=destination.model_copy(update={"active":False}))

    def test_non_human_identity_and_naive_timestamp_refused(self):
        for actor, time in ((None, NOW), ("client-input", NOW), (ACTOR, datetime(2026, 10, 17))):
            with self.subTest(actor=actor), self.assertRaises(DomainError):
                commands.edit_candidate(candidate(), PatchRequest(expected_version=1, changes=CandidatePatch(price_20gp="13")), actor_id=actor, at=time)

    def test_model_copy_cannot_bypass_approval_hash_validation(self):
        current = review(candidate()).candidate
        tampered = current.model_copy(update={"normalized_payload":QuotationValues(price_20gp="99")})
        with self.assertRaises(ValidationError):
            action_blockers(tampered, "APPLY", qingdao_origin_id=ORIGIN)

    def test_model_or_patch_cannot_set_review_states(self):
        with self.assertRaises(ValidationError):
            PatchRequest.model_validate({"expected_version":1, "changes":{"review_state":"APPROVED"}})

    def test_terminal_application_and_plan_states_cannot_be_reused(self):
        for enum, old, new in ((ApplicationState,"APPLIED","NOT_APPLIED"), (ApplicationState,"EXCLUDED","APPLIED"), (PlanState,"STALE","READY"), (PlanState,"CANCELLED","APPLIED"), (PlanState,"DRAFT","APPLIED")):
            with self.subTest(old=old, new=new), self.assertRaises(DomainError):
                require_transition(enum, old, new)
        require_transition(ApplicationState, "NOT_APPLIED", "APPLIED")
        require_transition(PlanState, "DRAFT", "READY")
        require_transition(PlanState, "READY", "APPLIED")


if __name__ == "__main__":
    unittest.main()
