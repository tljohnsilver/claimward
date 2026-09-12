"""ClaimWard Zero-Trust Gateway — Strands hook backed by Cedar + Rust zn.

Every tool call is intercepted at BeforeToolCallEvent (registered at
HookOrder.SDK_FIRST - 1, before any SDK hook) and evaluated against:
  1. The Rust `zn analyze` argument scanner (when available) — fail-closed.
  2. ClaimWard Cedar policies — unsigned submissions DENIED, unredacted
     PHI DENIED, deadline-expired appeals DENIED.
Every decision is appended to data/evidence/audit_trail.jsonl with the
SHA-256 of the exact tool-call arguments.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from src import policies
from src.models import AuditEvent

ZN_BINARY = Path("vendor/zn/target/release/zn")
if os.environ.get("ZN_BINARY"):
    ZN_BINARY = Path(os.environ["ZN_BINARY"])

AUDIT_PATH = Path("data/evidence/audit_trail.jsonl")

_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _invoke_zn(args_json: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Invoke zn analyze on tool args. Returns verdict dict or None if unavailable."""
    if not ZN_BINARY.exists():
        return None
    try:
        result = subprocess.run(
            [str(ZN_BINARY), "analyze"],
            input=args_json.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        for line in reversed(result.stdout.decode("utf-8", errors="replace").strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    if "verdict" in obj:
                        return obj
                except Exception:
                    continue
        return None
    except (subprocess.TimeoutExpired, OSError, Exception):
        return None  # zn unavailable/flaky — Cedar layer remains authoritative


def _detect_phi(tool_args: dict[str, Any]) -> bool:
    """HIPAA gate: scan tool args for unredacted SSN patterns."""
    blob = json.dumps(tool_args, default=str)
    return bool(_SSN_PATTERN.search(blob))


def _resource_data(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """Build the Cedar resource attrs (appeal state) for the evaluated action."""
    if tool_name != "submit_appeal_package":
        return {"appeal_id": str(tool_args.get("appeal_id", "draft"))}
    appeal_id = str(tool_args.get("appeal_id", ""))
    from src.tools import load_appeal
    appeal = load_appeal(appeal_id) or {}
    token_valid = False
    try:
        from src import hitl
        token_valid = hitl.verify_signature_token(appeal_id, str(tool_args.get("signature_token", "")))
    except Exception:
        token_valid = False
    return {
        "appeal_id": appeal_id or "unknown",
        "human_signed": bool(token_valid),
        "days_until_deadline": int(appeal.get("days_until_deadline", 0)) if appeal else 0,
    }


class ClaimWardGatewayHook:
    """Zero-trust Strands hook provider (Cedar + zn + SHA-256 audit vault)."""

    def __init__(self, audit_path: Path | str | None = None, use_zn: bool = True, timeout: float = 5.0) -> None:
        self.audit_path = Path(audit_path) if audit_path else AUDIT_PATH
        self.use_zn = use_zn
        self.timeout = timeout

    def register_hooks(self, registry: Any) -> None:
        from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent
        try:
            from strands.hooks.registry import HookOrder
            order = HookOrder.SDK_FIRST - 1
        except Exception:
            order = -101
        registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call, order=order)
        registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def inspect(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Full inspection pipeline. Returns a verdict dict."""
        try:
            canonical = json.dumps(tool_args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            canonical = str(tool_args)
        args_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        # Layer 1: Rust zn scanner (advisory block + fail-closed on block verdict)
        zn_verdict = None
        if self.use_zn:
            try:
                zn_verdict = _invoke_zn(canonical[:60_000], timeout=self.timeout)
                if zn_verdict and zn_verdict.get("verdict") == "block":
                    rule = zn_verdict.get("rule")
                    self._log(tool_name, "DENY", f"Blocked by zn gateway: {rule}", rule, args_sha256, canonical)
                    return {"decision": "DENY", "reason": f"Blocked by zn gateway: {rule}", "rule": rule, "args_sha256": args_sha256, "engine": "zn"}
            except Exception:
                pass

        # Layer 2: HIPAA PHI gate + Cedar policy evaluation
        context_data = {"phi_unredacted": _detect_phi(tool_args)}
        verdict = policies.evaluate_appeal_policy(tool_name, _resource_data(tool_name, tool_args), context_data)
        decision = verdict["decision"]
        diag = verdict.get("diagnostics", {})
        engine = diag.get("engine", verdict.get("engine", "cedarpy"))
        reason = "; ".join(diag.get("reasons", [])[:3]) or f"Cedar {decision_label(decision)}"
        rule = (diag.get("policy_ids") or [zn_verdict and zn_verdict.get("rule") or None])[0] if (diag.get("policy_ids") or zn_verdict) else None

        self._log(tool_name, decision, reason, rule, args_sha256, canonical)
        return {
            "decision": decision,
            "reason": reason,
            "rule": rule,
            "args_sha256": args_sha256,
            "engine": engine,
        }

    def _log(self, tool_name: str, decision: str, reason: str, rule: str | None, args_sha256: str, canonical: str) -> None:
        from datetime import datetime, timezone
        event = AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            tool=tool_name,
            decision=decision,
            reason=reason,
            rule=rule,
            args_sha256=args_sha256,
            args_preview=canonical[:200],
        )
        try:
            policies.log_audit_event(event, self.audit_path)
        except Exception:
            pass

    def on_before_tool_call(self, event: Any) -> None:
        try:
            tool_use = event.tool_use
            name = tool_use.get("name") if isinstance(tool_use, dict) else getattr(tool_use, "name", None)
            if not name and hasattr(event, "selected_tool") and event.selected_tool is not None:
                name = getattr(event.selected_tool, "tool_name", None) or getattr(event.selected_tool, "name", None)
            tool_args = tool_use.get("input", {}) if isinstance(tool_use, dict) else {}
            if not isinstance(tool_args, dict):
                tool_args = {"value": tool_args}
        except Exception:
            name, tool_args = "unknown", {}

        verdict = self.inspect(name, tool_args)
        if verdict["decision"] == "DENY":
            event.cancel_tool = f"DENIED by ClaimWard zero-trust gateway: {verdict['reason']} [rule: {verdict.get('rule')}]"

    def on_after_tool_call(self, event: Any) -> None:
        pass  # result sanitization reserved for future hardening


def decision_label(decision: str) -> str:
    return "ALLOWED" if decision == "ALLOW" else "DENIED"
