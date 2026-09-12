"""ClaimGuard Strands SDK tools — autonomous patient advocate workflow."""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from strands import tool

from src import hitl, policies
from src.models import AppealPackage, AuditEvent, ClinicalGuideline, DenialInfo

CRITERIA_PATH = Path("data/clinical_criteria/ncd_lcd_guidelines.json")
APPEALS_PATH = Path("data/evidence/appeals.jsonl")
SUBMITTED_PATH = Path("data/evidence/submitted_appeals.json")
SAMPLES_PATH = Path("data/sample_denials")


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_appeal(appeal_id: str) -> dict[str, Any] | None:
    """Load the most recent record for an appeal id."""
    if not APPEALS_PATH.exists():
        return None
    matches = []
    for line in APPEALS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rec = json.loads(line)
                if rec.get("appeal_id") == appeal_id:
                    matches.append(rec)
            except Exception:
                continue
    return matches[-1] if matches else None


def _days_until_deadline(filing_deadline_date: str) -> int:
    try:
        deadline = datetime.date.fromisoformat(str(filing_deadline_date))
        return (deadline - datetime.date.today()).days
    except Exception:
        return 0


def load_sample_denial(sample_id: str) -> str:
    """Load a sample denial letter by id (e.g. 'denial_01_mri_lumbar')."""
    if not sample_id.endswith(".json"):
        sample_id = f"{sample_id}.json"
    p = SAMPLES_PATH / sample_id
    if not p.exists():
        return json.dumps({"error": f"Sample not found: {sample_id}"})
    return p.read_text(encoding="utf-8")


@tool
def parse_denial_letter(raw_text: str) -> str:
    """Parse an insurer denial letter (EOB) into structured DenialInfo.

    Accepts raw narrative text or a full JSON denial record. Extracts claim
    number, CPT/ICD-10 codes, billed amount, denial reason, and the ERISA
    filing deadline.

    Args:
        raw_text: The raw denial letter text or JSON.
    """
    raw = raw_text.strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            denial = DenialInfo(
                denial_id=str(obj.get("denial_id", f"DEN-{datetime.date.today().isoformat()}")),
                patient_name=str(obj.get("patient_name", "Unknown Patient")),
                patient_dob=obj.get("patient_dob"),
                insurer=str(obj.get("insurer", "Unknown Insurer")),
                claim_number=str(obj.get("claim_number", "UNKNOWN")),
                date_of_service=obj.get("date_of_service"),
                denial_date=obj.get("denial_date"),
                erisa_deadline_days=int(obj.get("erisa_deadline_days", 180)),
                filing_deadline_date=str(obj.get("filing_deadline_date", "")),
                cpt_code=str(obj.get("cpt_code", "UNKNOWN")),
                cpt_description=str(obj.get("cpt_description", "")),
                icd10_code=str(obj.get("icd10_code", "")),
                icd10_description=str(obj.get("icd10_description", "")),
                billed_amount_cents=int(obj.get("billed_amount_cents", 0)),
                denial_code=obj.get("denial_code"),
                denial_reason=str(obj.get("denial_reason", "Unspecified denial reason")),
                clinical_facts=obj.get("clinical_facts", {}) or {},
            )
            return json.dumps({"parsed": True, "denial": json.loads(denial.model_dump_json())})
    except (json.JSONDecodeError, ValueError):
        pass

    # Free-text fallback extraction
    def _find(pattern: str, default: str = "") -> str:
        m = re.search(pattern, raw, re.IGNORECASE)
        return m.group(1).strip() if m else default

    billed = 0
    m_amt = re.search(r"\$([0-9,]+(?:\.[0-9]{2})?)", raw)
    if m_amt:
        billed = int(round(float(m_amt.group(1).replace(",", "")) * 100))
    m_cpt = re.search(r"\bCPT[:\s#]*([0-9]{4,5})", raw, re.IGNORECASE)
    denial = DenialInfo(
        denial_id=f"DEN-{datetime.date.today().isoformat()}",
        patient_name=_find(r"patient[:\s]+([A-Z][a-zA-Z .'-]+)", "Unknown Patient"),
        insurer=_find(r"(?:insurer|plan|paid by)[:\s]+([A-Za-z .&'-]+)", "Unknown Insurer"),
        claim_number=_find(r"(?:claim|reference)[# ]*(?:number|no\.?)?[:\s]*([A-Z0-9-]{6,})", "UNKNOWN"),
        filing_deadline_date=_find(r"(?:deadline|appeal by)[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2})"),
        cpt_code=m_cpt.group(1) if m_cpt else "UNKNOWN",
        denial_reason=_find(r"(?:reason|denial)[:\s]*([^\n]{10,300})", "Unspecified denial reason"),
        billed_amount_cents=billed,
    )
    return json.dumps({"parsed": True, "denial": json.loads(denial.model_dump_json())})


@tool
def query_clinical_criteria(cpt_code: str, diagnosis: str) -> str:
    """Query CMS NCD/LCD and specialty-society medical-necessity criteria for a procedure.

    Args:
        cpt_code: CPT or HCPCS code (e.g. 72148 for lumbar MRI, J0135 for Humira).
        diagnosis: ICD-10 code or diagnosis description.
    """
    if not CRITERIA_PATH.exists():
        return json.dumps({"found": False, "diagnosis": diagnosis, "reason": f"Guideline database missing: {CRITERIA_PATH}"})
    try:
        db = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"found": False, "diagnosis": diagnosis, "reason": f"Guideline database unreadable: {e}"})
    entry = db.get(cpt_code) if isinstance(db, dict) else None
    if isinstance(entry, dict):
        guideline = ClinicalGuideline(
            cpt_code=str(entry.get("cpt_code", cpt_code)),
            description=str(entry.get("description", "")),
            guideline_authority=str(entry.get("guideline_authority", "")),
            medical_necessity_criteria=[str(c) for c in entry.get("medical_necessity_criteria", [])],
            appeal_argument_template=str(entry.get("appeal_argument_template", "")),
            statutory_citations=[str(c) for c in entry.get("statutory_citations", [])],
        )
        return json.dumps({"found": True, "diagnosis": diagnosis, "guideline": json.loads(guideline.model_dump_json())})
    return json.dumps({"found": False, "diagnosis": diagnosis, "reason": f"No guideline entry for CPT {cpt_code} — escalate to treating physician for criteria"})


def _build_letter(d: dict[str, Any], g: dict[str, Any], patient_notes: str) -> str:
    """Compose the formal ERISA appeal letter with statutory citations."""
    facts = d.get("clinical_facts", {}) or {}
    criteria = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(g.get("medical_necessity_criteria", [])))
    cites = "\n".join(f"  - {c}" for c in g.get("statutory_citations", [])) or (
        "  - 29 U.S.C. § 1133 (ERISA § 503)\n  - 29 C.F.R. § 2560.503-1"
    )
    demands = [
        "Immediate reversal of the adverse benefit determination and authorization/payment of the denied claim.",
        "Provision of the complete claim file, including the identity and credentials of each reviewer, under 29 C.F.R. § 2560.503-1(h)(2)(iii)-(iv).",
        "Independent review by a board-certified specialist in the relevant discipline, per 29 C.F.R. § 2560.503-1(h)(3)(iii)-(iv).",
    ]
    demands_txt = "\n".join(f"  {i+1}. {x}" for i, x in enumerate(demands))
    notes = f"\n### Treating-Physician Addendum\n\n{patient_notes}" if patient_notes else ""
    amount = int(d.get("billed_amount_cents", 0)) / 100
    clinical_bullet = (
        facts.get("conservative_therapy_completed")
        or facts.get("contraindication_documented")
        or facts.get("disease_severity")
        or "See attached clinical records."
    )
    return f"""# FORMAL FIRST-LEVEL APPEAL OF ADVERSE BENEFIT DETERMINATION
## Filed under ERISA Section 503 — 29 U.S.C. § 1133 & 29 C.F.R. § 2560.503-1

**To (Claims & Appeals Department):** {d.get('insurer', 'Unknown Insurer')}
**From:** {d.get('patient_name', 'Patient')} and their authorized patient advocate
**Date:** {datetime.date.today().isoformat()}
**Re:** Claim {d.get('claim_number', '')} — Denial {d.get('denial_id', '')} — Procedure {d.get('cpt_code', '')} ({d.get('cpt_description', '')}) — {d.get('icd10_code', '')} — ${amount:,.2f}

---

### I. The Adverse Determination

On {d.get('denial_date', 'the denial date')}, the plan issued an adverse benefit determination (code {d.get('denial_code', 'n/a')}):

> {d.get('denial_reason', '')}

This letter constitutes the formal first-level appeal under ERISA Section 503 (29 U.S.C. § 1133) and
29 C.F.R. § 2560.503-1. The {d.get('erisa_deadline_days', 180)}-day filing deadline ({d.get('filing_deadline_date', '')}) is respected.

### II. Medical Necessity Is Established Under the Applicable Criteria

Authority relied upon: {g.get('guideline_authority', 'applicable clinical guidelines')}.

Applicable coverage criteria:
{criteria}

Documented clinical facts:
- Treating physician: {facts.get('treating_physician', 'on file')}
- {clinical_bullet}

The denial's stated basis is therefore factually refuted by the treating-physician documentation attached to this appeal.

### III. Legal Demands
{demands_txt}

### IV. Statutory & Clinical Citations
{cites}
{notes}

---

Respectfully submitted,

______________________________
{d.get('patient_name', 'Patient')} — Patient Signature (cryptographic SHA-256 attestation attached)

*Drafted autonomously by ClaimGuard from verified clinical guidelines. Reviewed and cryptographically signed by the patient before submission.*"""


@tool
def draft_erisa_appeal(denial_json: str, clinical_evidence: str, patient_notes: str = "") -> str:
    """Draft the formal first-level ERISA appeal package citing 29 U.S.C. § 1133
    and 29 C.F.R. § 2560.503-1, grounded in the matched clinical guideline.

    Args:
        denial_json: JSON from parse_denial_letter (structured denial).
        clinical_evidence: JSON from query_clinical_criteria (guideline match).
        patient_notes: Optional treating-physician addendum from the patient.
    """
    d_raw = json.loads(denial_json)
    d = d_raw.get("denial", d_raw)
    if clinical_evidence.strip():
        try:
            g_raw = json.loads(clinical_evidence)
            g = g_raw.get("guideline", g_raw) if isinstance(g_raw, dict) else {}
        except json.JSONDecodeError:
            g = {}
    else:
        g = {}

    clinical_facts = d.get("clinical_facts", {}) or {}
    clinical_summary = (
        f"{d.get('patient_name', 'Patient')}: {d.get('cpt_description') or d.get('cpt_code')} for "
        f"{d.get('icd10_description') or d.get('icd10_code')}. "
        f"{clinical_facts.get('conservative_therapy_completed') or clinical_facts.get('contraindication_documented') or clinical_facts.get('disease_severity', '')}"
    )
    letter = _build_letter(d, g, patient_notes)
    pkg = AppealPackage(
        appeal_id=f"APP-{d.get('denial_id', 'UNKNOWN')}",
        denial_id=str(d.get("denial_id", "")),
        patient_name=str(d.get("patient_name", "")),
        insurer=str(d.get("insurer", "")),
        clinical_summary=clinical_summary,
        legal_demands=[
            "Immediate reversal of adverse benefit determination",
            "Provision of full claim file including reviewer credentials under 29 C.F.R. § 2560.503-1(h)(2)(iii)",
            "Independent specialty review under 29 C.F.R. § 2560.503-1(h)(3)(iii)",
        ],
        appeal_letter_markdown=letter,
        human_signed=False,
        days_until_deadline=_days_until_deadline(d.get("filing_deadline_date", "")),
        status="pending_signature",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    rec = json.loads(pkg.model_dump_json())
    APPEALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APPEALS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return json.dumps(rec)


@tool
def request_patient_signature(appeal_id: str, appeal_draft: str) -> str:
    """Publish a HITL approval card: the patient must review and cryptographically
    sign the appeal before it can be submitted (Cedar-enforced).

    Args:
        appeal_id: Appeal package id.
        appeal_draft: The full appeal letter awaiting review.
    """
    rec = hitl.create_pending(appeal_id, appeal_draft)
    return json.dumps({
        "requested": True,
        "appeal_id": appeal_id,
        "status": rec["status"],
        "appeal_draft_sha256": rec["appeal_draft_sha256"],
        "message": "HITL: appeal paused — patient must review and sign in the portal before submission",
    })


@tool
def submit_appeal_package(appeal_id: str, signature_token: str, recipient: str = "insurer-claims-portal") -> str:
    """Submit the signed appeal package to the insurer. GATED by Cedar policy
    (human_signed == true and days_until_deadline >= 0) and verified against
    the patient's cryptographic signature token.

    Args:
        appeal_id: Appeal package id.
        signature_token: SHA-256 token issued after patient sign-off.
        recipient: Destination (insurer portal / fax endpoint).
    """
    appeal = load_appeal(appeal_id)
    if not appeal:
        return json.dumps({"submitted": False, "error": f"Appeal {appeal_id} not found"})

    token_valid = hitl.verify_signature_token(appeal_id, str(signature_token))
    resource_data = {
        "appeal_id": appeal_id,
        "human_signed": bool(token_valid),
        "days_until_deadline": int(appeal.get("days_until_deadline", 0)),
    }
    verdict = policies.evaluate_appeal_policy("submit_appeal_package", resource_data, {"phi_unredacted": False})
    # Log the Cedar verdict to the audit vault so the portal's Evidence Vault is live
    try:
        import hashlib as _h
        _canon = json.dumps({"appeal_id": appeal_id, "signature_token_present": bool(signature_token)}, sort_keys=True, separators=(",", ":"))
        policies.log_audit_event(AuditEvent(
            ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tool="submit_appeal_package",
            decision=verdict["decision"],
            reason="; ".join(verdict["diagnostics"].get("reasons", [])[:3]) or f"Cedar {verdict['decision']}",
            rule=(verdict["diagnostics"].get("policy_ids") or [None])[0],
            args_sha256=_h.sha256(_canon.encode("utf-8")).hexdigest(),
            args_preview=_canon[:200],
        ))
    except Exception:
        pass
    if verdict["decision"] != "ALLOW":
        return json.dumps({
            "submitted": False,
            "cedar": verdict,
            "reason": "HITL_REQUIRED — patient signature missing or invalid; submission blocked by the zero-trust gate",
        })

    record = {
        "appeal_id": appeal_id,
        "denial_id": appeal.get("denial_id"),
        "recipient": recipient,
        "signature_sha256": hitl.draft_hash(str(appeal.get("appeal_letter_markdown", ""))),
        "submitted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cedar_decision": verdict["decision"],
    }
    SUBMITTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = []
    if SUBMITTED_PATH.exists():
        try:
            data = json.loads(SUBMITTED_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = []
    data.append(record)
    SUBMITTED_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return json.dumps({"submitted": True, **record})
