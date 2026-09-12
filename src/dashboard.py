"""ClaimWard Patient Advocate Web Portal — FastAPI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src import hitl, policies
from src.agent import run_patient_appeal_cycle
from src.policies import load_audit_entries
from src.tools import APPEALS_PATH, load_appeal, load_sample_denial, submit_appeal_package

SRC_DIR = Path(__file__).resolve().parent
STATIC_DIR = SRC_DIR / "static"
AUDIT_PATH = Path("data/evidence/audit_trail.jsonl")

app = FastAPI(title="ClaimWard Patient Advocate Portal")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "agent": "claimward"}


@app.post("/api/denials/analyze")
def analyze_denial(payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest a denial letter (text or sample id), run the advocacy cycle,
    return the drafted appeal + pending patient signature card."""
    if payload.get("sample_id"):
        sample = str(payload["sample_id"])
        text = load_sample_denial(sample)
        if "error" in json.loads(text):
            raise HTTPException(status_code=404, detail=f"Sample not found: {sample}")
    elif payload.get("text"):
        text = str(payload["text"])
    else:
        raise HTTPException(status_code=400, detail="Provide 'text' or 'sample_id'")

    result = run_patient_appeal_cycle(text, auto_sign=False)
    if "error" in result:
        raise HTTPException(status_code=422, detail=str(result.get("error")))
    appeal = load_appeal(str(result["appeal_id"])) or {}
    return {
        "denial": {k: result.get(k) for k in ("denial_id", "patient_name", "insurer", "cpt_code", "billed_amount_cents")},
        "guideline_found": result.get("guideline_found"),
        "guideline_authority": result.get("guideline_authority"),
        "appeal_id": result.get("appeal_id"),
        "appeal_letter_markdown": appeal.get("appeal_letter_markdown", ""),
        "days_until_deadline": result.get("days_until_deadline"),
        "signature_card": hitl.load_card(str(result["appeal_id"])),
        "submission_blocked_reason": result.get("submission_block_reason"),
    }


@app.get("/api/appeals")
def list_appeals() -> list[dict[str, Any]]:
    p = Path(APPEALS_PATH)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        safe = dict(rec)
        letter = safe.pop("appeal_letter_markdown", "")
        safe["letter_preview"] = letter[:300]
        safe["card"] = hitl.load_card(safe.get("appeal_id", ""))
        out.append(safe)
    return list(reversed(out[-50:]))


@app.get("/api/appeals/{appeal_id}")
def get_appeal(appeal_id: str) -> dict[str, Any]:
    appeal = load_appeal(appeal_id)
    if not appeal:
        raise HTTPException(status_code=404, detail=f"Appeal {appeal_id} not found")
    appeal["card"] = hitl.load_card(appeal_id)
    return appeal


@app.post("/api/appeals/{appeal_id}/sign")
def sign_appeal(appeal_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Patient reviewed the appeal — cryptographically sign and submit (HITL)."""
    from src.tools import submit_appeal_package
    appeal = load_appeal(appeal_id)
    if not appeal:
        raise HTTPException(status_code=404, detail=f"Appeal {appeal_id} not found")
    draft = str(appeal.get("appeal_letter_markdown", ""))
    rec = hitl.sign_appeal(appeal_id, draft)
    token = str(rec["signature_token"])
    sub_res = json.loads(submit_appeal_package(appeal_id, token))
    if not sub_res.get("submitted"):
        raise HTTPException(status_code=422, detail=sub_res.get("reason") or sub_res.get("error") or "Submission blocked by zero-trust gate")
    return {
        "signed": True,
        "appeal_id": appeal_id,
        "signature_sha256": rec["appeal_draft_sha256"],
        "submitted": True,
        "cedar_decision": sub_res.get("cedar_decision"),
    }


@app.get("/api/evidence")
def evidence(limit: int = 100) -> list[dict[str, Any]]:
    return policies.load_audit_entries(limit=limit, audit_path=AUDIT_PATH)
