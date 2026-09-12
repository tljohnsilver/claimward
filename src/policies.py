"""Cedar policy layer for ClaimGuard — deterministic evaluation via cedarpy.

Loads src/policies/policies.cedar and evaluates tool calls against the
zero-trust patient-protection gate. Falls back to a minimal deterministic
evaluator of the same subset if cedarpy is unavailable (honestly documented).

Decision contract (evaluate_appeal_policy):
    {"decision": "ALLOW" | "DENY",
     "diagnostics": {"reasons": [...], "policy_ids": [...], "error": Optional[str]},
     "engine": "cedarpy" | "fallback"}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import AuditEvent

POLICIES_PATH = Path("src/policies/policies.cedar")
DEFAULT_AUDIT_PATH = Path("data/evidence/audit_trail.jsonl")

try:
    import cedarpy  # type: ignore
    _CEDAR_AVAILABLE = True
except ImportError:
    cedarpy = None  # type: ignore
    _CEDAR_AVAILABLE = False

_POLICIES_TEXT = ""
try:
    _POLICIES_TEXT = POLICIES_PATH.read_text(encoding="utf-8")
    cedarpy.PolicySet.from_str(_POLICIES_TEXT)  # validate parse once
except Exception:
    _POLICIES_TEXT = ""


def _diagnostics(result: Any) -> dict[str, Any]:
    """Extract human-meaningful reasons: annotated policy ids (e.g. deny_submit_unsigned)."""
    reasons: list[str] = []
    try:
        d = result.diagnostics
        raw = list(getattr(d, "reasons", []) or [])
        annot = getattr(d, "id_annotations_by_reason", None) or {}
        for rid in raw:
            label = annot.get(rid, rid)
            reasons.append(str(label))
    except Exception:
        pass
    return {"reasons": reasons, "policy_ids": reasons}


def _build_entities(resource_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Cedar entity for the appeal resource, with attrs referenced by policies."""
    rid = str(resource_data.get("appeal_id", "draft"))
    attrs = {
        "human_signed": bool(resource_data.get("human_signed", False)),
        "days_until_deadline": int(resource_data.get("days_until_deadline", 0)),
    }
    return [{"uid": {"type": "Appeal", "id": rid}, "attrs": attrs}]


def _fallback_evaluate(action: str, resource_data: dict[str, Any], context_data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback mirroring the policies.cedar subset."""
    if context_data.get("phi_unredacted"):
        return {"decision": "DENY", "diagnostics": {"reasons": ["phi_unredacted (fallback)"], "policy_ids": ["deny_phi_unredacted"]}}
    if action == "submit_appeal_package":
        if not resource_data.get("human_signed"):
            return {"decision": "DENY", "diagnostics": {"reasons": ["appeal not signed by patient (fallback)"], "policy_ids": ["deny_submit_unsigned"]}}
        if int(resource_data.get("days_until_deadline", 0)) < 0:
            return {"decision": "DENY", "diagnostics": {"reasons": ["ERISA filing deadline exceeded (fallback)"], "policy_ids": ["deny_submit_after_deadline"]}}
        return {"decision": "ALLOW", "diagnostics": {"reasons": ["signed appeal within deadline (fallback)"], "policy_ids": ["permit_signed_submit"]}}
    # read/draft actions always permitted
    return {"decision": "ALLOW", "diagnostics": {"reasons": ["permitted analysis/drafting action (fallback)"], "policy_ids": ["permit_research_draft"]}}


def evaluate_appeal_policy(action: str, resource_data: dict[str, Any], context_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a tool call against ClaimGuard Cedar policies.

    Args:
        action: tool name, e.g. "submit_appeal_package".
        resource_data: appeal attributes (appeal_id, human_signed, days_until_deadline).
        context_data: gateway context (phi_unredacted, ...).

    Appeal state (human_signed, days_until_deadline) is passed through Cedar
    context — the installed cedarpy build cannot deserialize attribute-bearing
    entities, and context is the proven supported channel.
    """
    ctx = dict(context_data or {})
    ctx.setdefault("human_signed", bool(resource_data.get("human_signed", False)))
    ctx.setdefault("days_until_deadline", int(resource_data.get("days_until_deadline", 0)))

    if _CEDAR_AVAILABLE and _POLICIES_TEXT:
        rid = str(resource_data.get("appeal_id", "draft"))
        request = {
            "principal": 'Agent::"claimguard"',
            "action": f'Action::"{action}"',
            "resource": f'Appeal::"{rid}"',
            "context": ctx,
        }
        try:
            result = cedarpy.is_authorized(request, _POLICIES_TEXT, "[]")
            decision_str = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
            diag = _diagnostics(result)
            return {
                "decision": "ALLOW" if decision_str == "Allow" else "DENY",
                "diagnostics": diag,
                "engine": "cedarpy",
            }
        except Exception as e:
            fb = _fallback_evaluate(action, resource_data, context_data)
            fb["diagnostics"]["engine_error"] = str(e)
            fb["engine"] = "fallback"
            return fb
    fb = _fallback_evaluate(action, resource_data, context_data)
    fb["engine"] = "fallback"
    return fb


def log_audit_event(event: AuditEvent, audit_path: Path | str = DEFAULT_AUDIT_PATH) -> dict[str, Any]:
    """Append one audit event to the JSONL vault. Returns the written record."""
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = event.model_dump()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_audit_entries(limit: int = 100, audit_path: Path | str = DEFAULT_AUDIT_PATH) -> list[dict[str, Any]]:
    p = Path(audit_path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return list(reversed(entries[-limit:]))
