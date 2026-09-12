"""ClaimWard agent factory + deterministic patient-appeal cycle."""
from __future__ import annotations

import json
import os
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel

from src.gateway import ClaimWardGatewayHook
from src.tools import (
    draft_erisa_appeal,
    parse_denial_letter,
    query_clinical_criteria,
    request_patient_signature,
    submit_appeal_package,
)

SYSTEM_PROMPT = (
    "You are ClaimWard, an autonomous patient advocate fighting algorithmic insurance denials.\n"
    "Workflow for each denial:\n"
    "1. parse_denial_letter to extract claim, CPT/ICD-10 codes, amounts, and the ERISA deadline.\n"
    "2. query_clinical_criteria for the denied procedure's CMS/LCD medical-necessity criteria.\n"
    "3. draft_erisa_appeal citing ERISA 29 U.S.C. § 1133 and 29 C.F.R. § 2560.503-1.\n"
    "4. request_patient_signature — the patient MUST review and sign before submission.\n"
    "5. Only after a valid signature token exists, submit_appeal_package.\n"
    "Never submit an appeal without the patient's cryptographic signature. "
    "Never transmit unredacted PHI (SSNs) anywhere."
)

SAMPLES_PATH = Path("data/sample_denials")


def build_claimguard_agent(evidence_path: str | None = None) -> Agent:
    """Create the configured Strands Agent with the zero-trust gateway hook."""
    model = BedrockModel(model_id="us.amazon.nova-micro-v1:0", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    gateway = ClaimWardGatewayHook(audit_path=evidence_path or "data/evidence/audit_trail.jsonl")
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[parse_denial_letter, query_clinical_criteria, draft_erisa_appeal, request_patient_signature, submit_appeal_package],
        hooks=[gateway],
    )


def resolve_denial_input(denial_input: str) -> str:
    """Accept raw text, a JSON record, or a sample id."""
    text = denial_input.strip()
    if text.endswith(".json"):
        p = SAMPLES_PATH / text
        if not p.exists():
            p = Path(text)
        if p.exists():
            return p.read_text(encoding="utf-8")
    return text


def run_patient_appeal_cycle(denial_input: str, auto_sign: bool = False) -> dict:
    """Run one deterministic patient-advocacy cycle over a denial.

    Does not require the LLM — directly implements the 5-stage workflow so
    tests and offline runs work without Bedrock. For LLM-driven runs, call
    the agent built by build_claimguard_agent().

    Args:
        denial_input: raw denial text, JSON record, or a sample id / path.
        auto_sign: if True, the patient's cryptographic signature is simulated
                   (portal demo / tests). If False, the appeal stops at the
                   HITL signature gate.

    Returns dict with the cycle outcome.
    """
    from src import hitl
    from src.tools import load_appeal

    raw = resolve_denial_input(denial_input)

    # 1. Ingestion
    parsed = json.loads(parse_denial_letter(raw))
    if not parsed.get("parsed"):
        return {"error": "failed to parse denial letter", "raw": raw[:200]}
    denial = parsed["denial"]

    # 2. Clinical guidelines match
    guideline_res = json.loads(query_clinical_criteria(str(denial.get("cpt_code", "")), str(denial.get("icd10_code", ""))))
    clinical_evidence = json.dumps(guideline_res)

    # 3. ERISA appeal drafted
    appeal_res = json.loads(draft_erisa_appeal(json.dumps({"denial": denial}), clinical_evidence))
    appeal_id = str(appeal_res["appeal_id"])
    appeal_draft = str(appeal_res["appeal_letter_markdown"])

    # 4. HITL: patient review & signature gate
    sig_res = json.loads(request_patient_signature(appeal_id, appeal_draft))
    submitted = False
    submission_block_reason = None

    if auto_sign:
        sign_rec = hitl.sign_appeal(appeal_id, appeal_draft)
        token = str(sign_rec["signature_token"])
        sub_res = json.loads(submit_appeal_package(appeal_id, token))
        submitted = bool(sub_res.get("submitted"))
        if not submitted:
            submission_block_reason = sub_res.get("reason") or sub_res.get("error")
    else:
        # Attempt submission without signature — must be blocked (proves the gate)
        sub_res = json.loads(submit_appeal_package(appeal_id, ""))
        submitted = bool(sub_res.get("submitted"))
        if not submitted:
            submission_block_reason = sub_res.get("reason") or sub_res.get("error")

    return {
        "denial_id": denial.get("denial_id"),
        "patient_name": denial.get("patient_name"),
        "insurer": denial.get("insurer"),
        "cpt_code": denial.get("cpt_code"),
        "billed_amount_cents": denial.get("billed_amount_cents"),
        "guideline_found": bool(guideline_res.get("found")),
        "guideline_authority": (guideline_res.get("guideline") or {}).get("guideline_authority") if guideline_res.get("found") else None,
        "appeal_id": appeal_id,
        "appeal_statutory_basis": appeal_res.get("statutory_basis"),
        "days_until_deadline": appeal_res.get("days_until_deadline"),
        "hitl_status": sig_res.get("status"),
        "submitted": submitted,
        "submission_block_reason": submission_block_reason,
    }
