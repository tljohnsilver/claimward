"""ClaimGuard core data models (Pydantic v2)."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class DenialInfo(BaseModel):
    """Structured representation of an insurer denial letter / EOB."""

    denial_id: str
    patient_name: str
    patient_dob: Optional[str] = None
    insurer: str
    claim_number: str
    date_of_service: Optional[str] = None
    denial_date: Optional[str] = None
    erisa_deadline_days: int = 180
    filing_deadline_date: str
    cpt_code: str
    cpt_description: str = ""
    icd10_code: str = ""
    icd10_description: str = ""
    billed_amount_cents: int = 0
    denial_code: Optional[str] = None
    denial_reason: str
    clinical_facts: dict[str, Any] = Field(default_factory=dict)


class ClinicalGuideline(BaseModel):
    """Medical-necessity criteria from CMS NCD/LCD or specialty-society sources."""

    cpt_code: str
    description: str = ""
    guideline_authority: str = ""
    medical_necessity_criteria: list[str] = Field(default_factory=list)
    appeal_argument_template: str = ""
    statutory_citations: list[str] = Field(default_factory=list)


class AppealPackage(BaseModel):
    """Formal first-level ERISA appeal package awaiting patient sign-off."""

    appeal_id: str
    denial_id: str
    patient_name: str
    insurer: str
    statutory_basis: str = "ERISA Section 503 (29 U.S.C. § 1133) & 29 C.F.R. § 2560.503-1"
    clinical_summary: str = ""
    legal_demands: list[str] = Field(default_factory=list)
    appeal_letter_markdown: str = ""
    human_signed: bool = False
    signature_sha256: Optional[str] = None
    days_until_deadline: int = 0
    status: str = "drafted"  # drafted | pending_signature | submitted
    created_at: str = ""


class HITLApprovalCard(BaseModel):
    """Patient-facing approval card — the strictest gate in the system."""

    appeal_id: str
    status: str = "pending"  # pending | signed | rejected
    appeal_draft_sha256: str = ""
    signature_token: Optional[str] = None
    requested_at: str = ""
    signed_at: Optional[str] = None
    reason: str = "Patient must review and cryptographically sign before submission (ERISA § 503 patient authorization)"


class AuditEvent(BaseModel):
    """One entry in the immutable SHA-256 audit vault."""

    ts: str
    tool: str
    decision: str  # ALLOW | DENY
    reason: str
    rule: Optional[str] = None
    args_sha256: str = ""
    args_preview: str = ""
    engine: str = "cedarpy"  # cedarpy | fallback
