"""HITL — patient signature gate for ClaimWard.

Issues and verifies SHA-256 signature tokens for approved patient sign-offs.
Pending records: data/evidence/pending_signatures.json (JSONL).
Token = SHA-256(appeal_id | appeal_draft_sha256) — deterministic and bound to
the exact appeal draft the patient reviewed.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

PENDING_PATH = Path("data/evidence/pending_signatures.json")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft_hash(appeal_draft: str) -> str:
    return _sha256(appeal_draft)


def _token_for(appeal_id: str, appeal_draft_sha256: str) -> str:
    return _sha256(f"claimguard::signature::{appeal_id}::{appeal_draft_sha256}")


def _load_all(path: Path | str = PENDING_PATH) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def _append(entry: dict[str, Any], path: Path | str = PENDING_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _latest_for(appeal_id: str, path: Path | str = PENDING_PATH) -> dict[str, Any] | None:
    matches = [e for e in _load_all(path) if e.get("appeal_id") == appeal_id]
    return matches[-1] if matches else None


def create_pending(appeal_id: str, appeal_draft: str, path: Path | str = PENDING_PATH) -> dict[str, Any]:
    """Create (or refresh) a pending HITL signature card for an appeal."""
    dh = draft_hash(appeal_draft)
    entry = {
        "appeal_id": appeal_id,
        "status": "pending",
        "appeal_draft_sha256": dh,
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "signed_at": None,
        "signature_token": None,
    }
    _append(entry, path)
    return entry


def sign_appeal(appeal_id: str, appeal_draft: str, path: Path | str = PENDING_PATH) -> dict[str, Any]:
    """Patient reviewed and signed — issue the cryptographic token.

    Returns the signed record including the signature_token.
    """
    dh = draft_hash(appeal_draft)
    token = _token_for(appeal_id, dh)
    entry = {
        "appeal_id": appeal_id,
        "status": "signed",
        "appeal_draft_sha256": dh,
        "signature_token": token,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _append(entry, path)
    return entry


def _expected_token(appeal_id: str, path: Path | str = PENDING_PATH) -> str | None:
    rec = _latest_for(appeal_id, path)
    if rec and rec.get("status") == "signed":
        return rec.get("signature_token")
    return None


def verify_signature_token(appeal_id: str, token: str, path: Path | str = PENDING_PATH) -> bool:
    """Verify a signature token against the signed HITL record."""
    if not token:
        return False
    expected = _expected_token(appeal_id, path)
    if expected is None:
        return False
    return _sha256(token) == _sha256(expected) and token == expected


def is_signed(appeal_id: str, appeal_draft_sha256: str | None = None, path: Path | str = PENDING_PATH) -> bool:
    rec = _latest_for(appeal_id, path)
    if not rec or rec.get("status") != "signed":
        return False
    if appeal_draft_sha256 is not None and rec.get("appeal_draft_sha256") != appeal_draft_sha256:
        return False
    return True


def load_card(appeal_id: str, path: Path | str = PENDING_PATH) -> dict[str, Any]:
    rec = _latest_for(appeal_id, path)
    if not rec:
        return {"appeal_id": appeal_id, "status": "none", "appeal_draft_sha256": ""}
    safe = dict(rec)
    safe.pop("signature_token", None)  # never leak the token to the UI
    return safe
