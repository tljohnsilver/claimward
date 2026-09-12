"""Cedar policy tests — ClaimGuard zero-trust gates."""
from __future__ import annotations

from src.policies import evaluate_appeal_policy


def _resource(signed: bool, days: int, appeal_id: str = "APP-TEST-1") -> dict:
    return {"appeal_id": appeal_id, "human_signed": signed, "days_until_deadline": days}


def test_unsigned_submission_is_denied():
    verdict = evaluate_appeal_policy("submit_appeal_package", _resource(signed=False, days=30), {"phi_unredacted": False})
    assert verdict["decision"] == "DENY"
    assert any("signed" in r.lower() for r in verdict["diagnostics"]["reasons"])


def test_missing_signature_attr_is_denied():
    verdict = evaluate_appeal_policy("submit_appeal_package", {"appeal_id": "APP-TEST-1"}, {"phi_unredacted": False})
    assert verdict["decision"] == "DENY"


def test_signed_submission_within_deadline_is_allowed():
    verdict = evaluate_appeal_policy("submit_appeal_package", _resource(signed=True, days=42), {"phi_unredacted": False})
    assert verdict["decision"] == "ALLOW"


def test_signed_submission_at_deadline_boundary_is_allowed():
    verdict = evaluate_appeal_policy("submit_appeal_package", _resource(signed=True, days=0), {"phi_unredacted": False})
    assert verdict["decision"] == "ALLOW"


def test_signed_but_overdue_submission_is_denied():
    verdict = evaluate_appeal_policy("submit_appeal_package", _resource(signed=True, days=-5), {"phi_unredacted": False})
    assert verdict["decision"] == "DENY"


def test_unredacted_phi_is_denied():
    verdict = evaluate_appeal_policy(
        "parse_denial_letter",
        {"appeal_id": "APP-TEST-1"},
        {"phi_unredacted": True},
    )
    assert verdict["decision"] == "DENY"


def test_phi_gate_overrides_permit():
    # Even a permitted action is blocked when unredacted PHI is present
    verdict = evaluate_appeal_policy(
        "query_clinical_criteria",
        {"appeal_id": "APP-TEST-1"},
        {"phi_unredacted": True},
    )
    assert verdict["decision"] == "DENY"


def test_research_and_drafting_actions_are_permitted():
    for action in ("parse_denial_letter", "query_clinical_criteria", "draft_erisa_appeal", "request_patient_signature"):
        verdict = evaluate_appeal_policy(action, {"appeal_id": "APP-TEST-1"}, {"phi_unredacted": False})
        assert verdict["decision"] == "ALLOW", f"{action} should be ALLOW, got {verdict}"


def test_diagnostics_present():
    verdict = evaluate_appeal_policy("submit_appeal_package", _resource(signed=False, days=30), {"phi_unredacted": False})
    assert "diagnostics" in verdict and isinstance(verdict["diagnostics"], dict)
    assert "engine" in verdict
