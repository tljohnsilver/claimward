# Building an Autonomous Patient Advocate with Strands Agents SDK, Amazon Bedrock, and Cedar Zero-Trust Policies

*Inside ClaimGuard: an agent that deciphers insurance denials, matches CMS clinical criteria, drafts statutory ERISA § 503 appeals — and structurally cannot submit anything without the patient's cryptographic signature.*

---

## The problem agents are uniquely shaped to solve

American insurers deny **49 million claims a year**, increasingly via bulk algorithms — Cigna's PxDx processes denials in **~1.2 seconds** with no meaningful physician review (ProPublica). **$220B in medical debt** hangs over US households. And **99.8% of denied patients never appeal**, even though **60–90% of appeals succeed** when they're filed properly.

Why the gap? A winning appeal is a *legal document wrapped around a clinical argument*: extract the CPT/ICD-10 codes from the EOB, retrieve the CMS LCD medical-necessity criteria, cite **29 U.S.C. § 1133** (ERISA § 503 full-and-fair-review) and **29 C.F.R. § 2560.503-1**, demand the reviewer's credentials, file within 180 days. A tired patient has none of that machinery.

That machinery is exactly what an LLM agent can assemble. But it raises the human question every agentic system must answer: **what do we do about the part only a human may do?** An appeal is a sworn medical statement in the patient's name. No agent should submit one autonomously.

This article shows how ClaimGuard answers it with the Strands Agents SDK's hook system and Cedar: the agent drafts everything, and the *architecture itself* forbids it from signing or submitting.

## The architecture in one paragraph

A Strands `Agent` (Amazon Bedrock Nova Micro) with five tools — `parse_denial_letter`, `query_clinical_criteria`, `draft_erisa_appeal`, `request_patient_signature`, `submit_appeal_package` — carries the workflow. A gateway hook registered at **`BeforeToolCallEvent` with order `SDK_FIRST - 1`** intercepts every tool call before execution, runs a Rust argument scanner (`zn`, fail-closed) and Cedar policies, and cancels the call unless policy permits. Patient sign-off issues a SHA-256 token bound to the exact appeal draft; Cedar's `human_signed` context is derived from verifying that token. Every verdict lands in an append-only SHA-256 audit vault.

## The enforcement point: `BeforeToolCallEvent` at `SDK_FIRST - 1`

The non-obvious Strands trick: hooks are *mutable and orderable*. Registering at `SDK_FIRST - 1` puts your gate ahead of every SDK hook — and setting `event.cancel_tool` means the tool never executes:

```python
# src/gateway.py
class ClaimGuardGatewayHook:
    """Zero-trust Strands hook provider (Cedar + zn + SHA-256 audit vault)."""

    def register_hooks(self, registry) -> None:
        from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent
        from strands.hooks.registry import HookOrder
        registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call,
                              order=HookOrder.SDK_FIRST - 1)
        registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_tool_call(self, event) -> None:
        name, tool_args = self._extract(event)
        verdict = self.inspect(name, tool_args)
        if verdict["decision"] == "DENY":
            event.cancel_tool = (
                f"DENIED by ClaimGuard zero-trust gateway: {verdict['reason']} "
                f"[rule: {verdict.get('rule')}]"
            )
```

The inspection pipeline layers two gates:

```python
# src/gateway.py (excerpt)
def inspect(self, tool_name, tool_args):
    canonical = json.dumps(tool_args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    args_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # Layer 1: Rust zn scanner — advisory block, deterministic, fail-closed
    zn_verdict = _invoke_zn(canonical[:60_000]) if self.use_zn else None
    if zn_verdict and zn_verdict.get("verdict") == "block":
        self._log(tool_name, "DENY", f"Blocked by zn gateway: {zn_verdict.get('rule')}",
                  zn_verdict.get("rule"), args_sha256, canonical)
        return {"decision": "DENY", "reason": "Blocked by zn gateway", ...}

    # Layer 2: HIPAA PHI gate + Cedar policy evaluation
    context_data = {"phi_unredacted": _detect_phi(tool_args)}   # SSN regex
    verdict = policies.evaluate_appeal_policy(
        tool_name, _resource_data(tool_name, tool_args), context_data)
    self._log(tool_name, verdict["decision"], reason, rule, args_sha256, canonical)
    return verdict
```

Two things worth copying for any agent that acts in the world:

1. **Interpose a verdict between intent and action.** The LLM proposes `submit_appeal_package`; the hook decides whether that call exists. If Cedar says no, there is no tool call — not a tool call we didn't like.
2. **Fail closed everywhere.** zn timeouts and Cedar engine exceptions resolve to DENY, and `_detect_phi` scanning for SSN patterns is a deny-all override.

## The policy layer: patient authority as authorization-as-code

Cedar gives us the patient-protection contract in a form that is reviewable, testable, and deterministic:

```cedar
// src/policies/policies.cedar

// 1. Permit non-destructive clinical analysis and appeal drafting
permit(
    principal,
    action in [
        Action::"parse_denial_letter",
        Action::"query_clinical_criteria",
        Action::"draft_erisa_appeal",
        Action::"request_patient_signature"
    ],
    resource
);

// 2. Strict Patient Gate: forbid final submission unless explicitly approved & signed
forbid(
    principal,
    action == Action::"submit_appeal_package",
    resource
) unless {
    resource.human_signed == true &&
    resource.days_until_deadline >= 0
};

// 3. Explicit complement: signed appeals within the ERISA deadline may be submitted
permit(
    principal,
    action == Action::"submit_appeal_package",
    resource
) when {
    resource.human_signed == true &&
    resource.days_until_deadline >= 0
};

// 4. HIPAA Gate: forbid transmitting unredacted patient identifiers
forbid(
    principal,
    action,
    resource
) when {
    context.phi_unredacted == true
};
```

Read that as three laws: **the agent may research and draft freely; it may never submit an unsigned or time-expired appeal; it may never transmit unredacted PHI.** Cedar's default-deny semantics plus the explicit complement (policy 3) make the signed-submission decision correct in both directions — the forbid fires for unsigned appeals, the permit fires only for signed, timely ones, and everything else falls to default-deny.

Evaluation goes through a thin wrapper that builds the Cedar entity from the appeal's actual state:

```python
# src/policies.py (excerpt)
def evaluate_appeal_policy(action: str, resource_data: dict, context_data: dict) -> dict:
    rid = str(resource_data.get("appeal_id", "draft"))
    request = {
        "principal": 'Agent::"claimguard"',
        "action": f'Action::"{action}"',
        "resource": f'Appeal::"{rid}"',
        "context": dict(context_data or {}),
    }
    entities = [{
        "uid": {"type": "Appeal", "id": rid},
        "attrs": {
            "human_signed": bool(resource_data.get("human_signed", False)),
            "days_until_deadline": int(resource_data.get("days_until_deadline", 0)),
        },
    }]
    result = cedarpy.is_authorized(request, _POLICIES_TEXT, entities)
    decision = "ALLOW" if result.decision.value == "Allow" else "DENY"
    return {"decision": decision, "diagnostics": {...policy ids and reasons...}}
```

## The signature chain: approval bound to exact bytes

The subtle trust problem in HITL: an approval stored as "appeal X approved" is forgeable — a later call with *different* arguments rides the old approval. ClaimGuard binds the token to the draft's hash:

```python
# src/hitl.py
def _token_for(appeal_id: str, appeal_draft_sha256: str) -> str:
    return _sha256(f"claimguard::signature::{appeal_id}::{appeal_draft_sha256}")

def sign_appeal(appeal_id, appeal_draft, path=PENDING_PATH):
    dh = draft_hash(appeal_draft)
    token = _token_for(appeal_id, dh)
    _append({"appeal_id": appeal_id, "status": "signed",
             "appeal_draft_sha256": dh, "signature_token": token, ...})
    return ...
```

And the gateway derives Cedar's `human_signed` context *from token verification*, not from any flag the agent could set:

```python
# src/gateway.py (excerpt)
def _resource_data(tool_name, tool_args):
    if tool_name != "submit_appeal_package":
        return {"appeal_id": tool_args.get("appeal_id", "draft")}
    token_valid = hitl.verify_signature_token(
        appeal_id, tool_args.get("signature_token", ""))
    return {
        "appeal_id": appeal_id,
        "human_signed": bool(token_valid),
        "days_until_deadline": appeal.get("days_until_deadline", 0),
    }
```

Approving one letter unlocks exactly one submission of exactly those bytes. Forging the token, or changing a word of the letter after signing, fails verification — and Cedar denies.

## The tools: statutory-grade output from grounded sources

The drafting tool composes the appeal from *structured* inputs — the parsed denial and the matched guideline — rather than free-form generation, so every citation traces to the local CMS/LCD database:

```python
# src/tools.py (excerpt)
@tool
def draft_erisa_appeal(denial_json: str, clinical_evidence: str, patient_notes: str = "") -> str:
    """Draft the formal first-level ERISA appeal package citing 29 U.S.C. § 1133
    and 29 C.F.R. § 2560.503-1, grounded in the matched clinical guideline."""
    d = json.loads(denial_json).get("denial", {})
    g = json.loads(clinical_evidence).get("guideline", {})
    letter = _build_letter(d, g, patient_notes)
    pkg = AppealPackage(
        appeal_id=f"APP-{d.get('denial_id')}",
        ...,
        human_signed=False,
        days_until_deadline=_days_until_deadline(d["filing_deadline_date"]),
        status="pending_signature",
    )
    ...
```

The letter quotes the adverse determination, maps the documented clinical facts onto the guideline's explicit coverage criteria, and issues the legal demands a payor's appeals unit will recognize — including the reviewer-credential disclosure required by § 2560.503-1(h)(2)(iii) and independent specialty review under § 2560.503-1(h)(3)(iii).

## Proof: the test suite and the deny log

The Cedar matrix and the end-to-end cycle are both covered, with no AWS credentials required:

```
tests/test_cedar_policies.py
  test_unsigned_submission_is_denied           DENY (deny_submit_unsigned)
  test_signed_submission_within_deadline_is_allowed   ALLOW
  test_signed_but_overdue_submission_is_denied DENY
  test_unredacted_phi_is_denied                DENY (HIPAA gate)
  test_phi_gate_overrides_permit               DENY even for permitted actions

tests/test_agent_workflow.py
  test_full_cycle_unsigned_blocks_submission   HITL holds, letter drafted
  test_full_cycle_signed_submission_succeeds   token issued → submitted + SHA-256
  test_hitl_token_verification_and_rejection   forged tokens rejected
  test_gateway_denies_unsigned_submit_and_logs_audit   evidence vault rows
```

And the audit trail is the system telling on itself — every verdict, hashed:

```json
{"ts": "2026-09-12T13:24:31Z", "tool": "submit_appeal_package", "decision": "DENY",
 "reason": "appeal not signed by patient", "rule": "deny_submit_unsigned",
 "args_sha256": "3f9c1e…", "args_preview": "{\"appeal_id\": \"APP-DEN-2026-0842\"…"}
```

## Deployment and what's next

The AgentCore ARM64 container image is ready; the FastAPI patient portal (dark obsidian/cobalt/teal brand kit) runs anywhere Python does:

```bash
uvicorn src.dashboard:app --host 0.0.0.0 --port 8080
```

Next on the list: fax/email delivery into real insurer claims queues, a treating-physician counter-signature chain, external-review escalation under ACA § 2719, and expanding the CMS NCD/LCD guideline coverage.

## Takeaways for agent builders

1. **Split the workflow at reversibility, not capability.** Everything the agent can do alone, it should do alone. The one irreversible, legally-binding act gets a cryptographic human gate.
2. **Put the gate where intent becomes action.** `BeforeToolCallEvent` at `SDK_FIRST - 1` is the cleanest enforcement point the Strands SDK offers.
3. **Bind approvals to bytes.** A SHA-256 over the canonical artifact turns "the human said yes" into a checkable fact.
4. **Make the audit trail the UI.** Patients (and judges) trust what they can see: every ALLOW and DENY, hashed, in plain sight.

---

*ClaimGuard is MIT-licensed: [github.com/tljohnsilver/claimward](https://github.com/tljohnsilver/claimward) — built for the AWS "Agents for Humans" hackathon (Everyday Agents / Good Neighbor track).*
