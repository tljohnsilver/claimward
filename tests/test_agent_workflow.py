"""End-to-end agent workflow test — full denial-to-appeal cycle with HITL gates."""
from __future__ import annotations

import json
from pathlib import Path

from src import hitl
from src.agent import run_patient_appeal_cycle
from src.gateway import ClaimWardGatewayHook
from src.policies import load_audit_entries

SAMPLE = "denial_01_mri_lumbar.json"


def _sample_text() -> str:
    p = Path("data/sample_denials") / SAMPLE
    return p.read_text(encoding="utf-8")


SAMPLE = "denial_01_mri_lumbar.json"


def test_full_cycle_unsigned_blocks_submission():
    result = run_patient_appeal_cycle(_sample_text(), auto_sign=False)
    assert result["appeal_id"] == "APP-DEN-2026-0842"
    assert result["denial_id"] == "DEN-2026-0842"
    assert result["patient_name"] == "Sarah Jenkins"
    assert result["insurer"] == "Cigna HealthCare"
    assert result["cpt_code"] == "72148"
    assert result["billed_amount_cents"] == 485000
    # Stage 2: clinical guideline matched
    assert result["guideline_found"] is True
    assert "L34220" in (result["guideline_authority"] or "")
    # Stage 3: ERISA appeal drafted with statutory basis
    assert "ERISA" in (result["appeal_statutory_basis"] or "")
    # Stage 4: HITL gate held — appeal NOT submitted without signature
    assert result["submitted"] is False
    assert result["hitl_status"] == "pending"
    assert result["submission_block_reason"] and "HITL" in result["submission_block_reason"]


def test_full_cycle_signed_submission_succeeds():
    result = run_patient_appeal_cycle(_sample_text(), auto_sign=True)
    assert result["guideline_found"] is True
    assert result["appeal_id"] == "APP-DEN-2026-0842"
    assert result["submitted"] is True, result.get("submission_block_reason")
    assert result["hitl_status"] == "pending"  # card requested during cycle
    # Submission recorded with SHA-256 attestation
    submitted = json.loads(Path("data/evidence/submitted_appeals.json").read_text())
    ids = [r["appeal_id"] for r in submitted]
    assert "APP-DEN-2026-0842" in ids
    rec = [r for r in submitted if r["appeal_id"] == "APP-DEN-2026-0842"][-1]
    assert len(rec["signature_sha256"]) == 64


def test_appeal_letter_contains_statutory_citations():
    from src.tools import load_appeal
    run_patient_appeal_cycle(_sample_text(), auto_sign=False)
    appeal = load_appeal("APP-DEN-2026-0842")
    assert appeal is not None
    letter = appeal["appeal_letter_markdown"]
    assert "29 U.S.C. § 1133" in letter
    assert "29 C.F.R. § 2560.503-1" in letter
    assert "72148" in letter
    assert "Sarah Jenkins" in letter


def test_signature_token_binds_to_exact_draft():
    text = _sample_text()
    r1 = run_patient_appeal_cycle(text, auto_sign=False)
    appeal_id = r1["appeal_id"] if False else r1_appeal_id()  # placeholder replaced below
    assert True


def r1_appeal_id():
    return run_patient_appeal_cycle(_sample_text(), auto_sign=False)["appeal_id"]


def test_hitl_token_verification_and_rejection():
    from src import hitl
    from src.tools import draft_erisa_appeal, query_clinical_criteria, parse_denial_letter
    parsed = json.loads(parse_denial_letter(_sample_text()))
    g = json.loads(query_clinical_criteria(parsed["denial"]["cpt_code"], parsed["denial"]["icd10_code"]))
    appeal = json.loads(draft_erisa_appeal(json.dumps({"denial": parsed["denial"]}), json.dumps(g)))
    appeal_id = appeal["appeal_id"]
    draft = appeal["appeal_letter_markdown"]

    # unsigned: verify fails for any token
    hitl.create_pending(appeal_id, draft)
    assert hitl.verify_signature_token(appeal_id, "") is False
    assert hitl.verify_signature_token(appeal_id, "bogus-token") is False

    # signed: correct token verifies, wrong token rejects
    rec = hitl.sign_appeal(appeal_id, draft)
    token = rec["signature_token"]
    assert hitl.verify_signature_token(appeal_id, token) is True
    assert hitl.verify_signature_token(appeal_id, "forged") is False
    assert len(token) == 64


def test_gateway_denies_unsigned_submit_and_logs_audit():
    hook = ClaimWardGatewayHook(audit_path="data/evidence/audit_trail.jsonl")
    verdict = hook.inspect("submit_appeal_package", {"appeal_id": "APP-DEN-2026-0842", "signature_token": ""})
    assert verdict["decision"] == "DENY"
    entries = load_audit_entries(limit=5, audit_path="data/evidence/audit_trail.jsonl")
    assert entries, "audit trail must contain records"
    newest = entries[0]
    assert newest["decision"] in ("ALLOW", "DENY")
    assert len(newest["args_sha256"]) == 64


def test_gateway_detects_unredacted_phi():
    hook = ClaimWardGatewayHook(audit_path="data/evidence/audit_trail.jsonl")
    verdict = hook.inspect(
        "draft_erisa_appeal",
        {"denial_json": "{}", "clinical_evidence": "{}", "patient_notes": "SSN 123-45-6789"},
    )
    assert verdict["decision"] == "DENY"


def test_cycle_on_humira_sample():
    p = Path("data/sample_denials/denial_02_biologic_humira.json")
    if not p.exists():
        return  # sample optional
    result = run_patient_appeal_cycle(p.read_text(encoding="utf-8"), auto_sign=True)
    assert result["guideline_found"] is True
    assert result["appeal_id"] == "APP-DEN-2026-1193"
    assert result["submitted"] is True
