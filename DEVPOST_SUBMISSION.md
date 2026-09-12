# Devpost Submission — "Agents for Humans" Hackathon (Everyday Agents / Good Neighbor Track)

## Project Title

**ClaimGuard: The Autonomous Patient Advocate That Fights Algorithmic Insurance Denials**

## Tagline (<200 chars)

An autonomous agent that deciphers denials, matches CMS clinical criteria, drafts the ERISA § 503 appeal — and never submits without the patient's cryptographic signature.

## Inspiration

It starts with a letter most Americans know too well: *"After careful review, your claim has been denied."*

Behind it sits a machine. Insurers deny **49 million claims a year**; Cigna's PxDx algorithm rejects claims in **1.2 seconds** with no physician review, and ProPublica documented doctors "reviewing" thousands per month. Meanwhile **$220 billion in medical debt** weighs on US families, and **99.8% of denied patients never appeal** — because a winning appeal is a legal document: CPT codes, CMS clinical-necessity criteria, ERISA § 503 statutory citations, filed within 180 days. Who has the energy for that while sick or caring for someone who is?

The cruelest part: **60–90% of appealed denials are overturned.** The evidence was always there. The fight is just designed to be unwinnable by one exhausted human.

But families can't just outsource the fight to a bot. An appeal is a sworn medical statement bearing the patient's name — and no one wants an AI mailing their unredacted health data anywhere. That tension became our design law: **build the advocate that can do everything except the one thing only the patient may do — sign.**

## What it does

ClaimGuard runs a 5-stage autonomous advocacy workflow:

1. **Deciphers the denial letter** — extracts claim number, CPT/ICD-10 codes, billed amount, denial reason, and the 180-day ERISA filing deadline from raw letter text or structured records.
2. **Retrieves the clinical standard** — matches the denied procedure (CPT 72148 lumbar MRI, J0135 Humira, …) against CMS NCD/LCD and specialty-society medical-necessity criteria, finding the exact criteria the insurer's own denial logic must meet.
3. **Drafts the formal ERISA appeal** — a 2-page statutory package quoting the adverse determination, mapping documented clinical facts onto the coverage criteria, and citing 29 U.S.C. § 1133 and 29 C.F.R. § 2560.503-1 — with concrete legal demands like disclosure of the reviewer's identity and credentials under § 2560.503-1(h)(2)(iii).
4. **Enforces the patient signature gate (HITL)** — submission is **Cedar-forbidden** until the patient reviews the full letter in the web portal and signs. The signature issues a SHA-256 token cryptographically bound to the exact draft reviewed.
5. **Protects privacy and proves everything** — a HIPAA gate hard-blocks any tool call carrying unredacted PHI (SSN patterns); every Cedar verdict is appended to an immutable SHA-256 evidence vault visible live in the portal.

Demo: a Cigna PxDx-style denial of a $4,850 lumbar MRI (patient completed 8 weeks of failed physical therapy, has a progressive motor deficit) becomes a fully-cited appeal in seconds — paused until the patient signs.

## How we built it

- **Strands Agents SDK** as the agent backbone: a Bedrock-backed `Agent` with five tools (`parse_denial_letter`, `query_clinical_criteria`, `draft_erisa_appeal`, `request_patient_signature`, `submit_appeal_package`). Our `ClaimGuardGatewayHook` registers **`BeforeToolCallEvent` at `HookOrder.SDK_FIRST - 1`** — before every SDK hook — so the zero-trust gate evaluates the decision exactly when the LLM's intent becomes an action, and cancels the call if policy says no.
- **Amazon Bedrock (Nova Micro)** for reasoning over denial letters and clinical criteria.
- **Cedar policies** (`cedarpy` 4.8.7) as authorization-as-code: unsigned submissions and deadline-expired appeals are forbidden; `context.phi_unredacted == true` denies *any* action (HIPAA gate); a complementary permit policy allows signed, timely submissions.
- **A Rust deterministic gateway (`zn`)** scans tool-call arguments (fail-closed) as the outer layer before Cedar evaluation.
- **HITL signature chain**: pending signature records in `pending_signatures.json`; token = SHA-256(appeal_id | draft_sha256); submission verifies the token before deriving Cedar's `human_signed` context — approval is bound to the exact bytes the patient reviewed.
- **Pydantic v2 models** (`DenialInfo`, `ClinicalGuideline`, `AppealPackage`, `HITLApprovalCard`, `AuditEvent`); FastAPI patient portal with a 5-stage live workflow timeline and evidence-vault log.

## Challenges we ran into

- **Balancing autonomy with patient authority.** An agent that asks permission for every step saves nothing; one that submits freely is unsafe. We enforced by reversibility: everything except the *irreversible, legally-binding act* flows autonomously; submission alone requires the patient's cryptographic sign-off.
- **Making approval unforgeable.** Tool-name-level approval is spoofable. We hash the canonical appeal draft and bind the token to it — a signed approval for one letter can never authorize a different one.
- **Fail-closed enforcement.** Missing Cedar attributes, engine errors, or a flaky zn binary must produce DENY, never a silent allow. Each failure mode has an explicit test.
- **Grounding appeals in real criteria, not hallucinated citations.** The drafting tool composes the letter from a local CMS/LCD guideline database (criteria, argument template, statutory citations), so every factual claim traces to a source a human can check.

## Accomplishments that we're proud of

- **100% of the automated test suite passing** — Cedar gate matrix (unsigned/signed/expired/PHI/missing-attrs) plus full end-to-end cycles on real denial patterns (Cigna MRI, UnitedHealth Humira).
- **A provable HITL gate**: attempts to submit unsigned appeals are denied by Cedar at `BeforeToolCallEvent` *before any tool executes*, with the denial's SHA-256 written to the evidence vault.
- **A complete, empathetic patient portal** — dark, high-contrast, brand-kit themed — that walks a stressed patient from denial letter to signed, submitted ERISA appeal in one session, with the audit trail visible at all times.
- **Statutory-grade output**: every drafted appeal cites 29 U.S.C. § 1133, 29 C.F.R. § 2560.503-1, and the applicable CMS/specialty-society criteria.

## What we learned

- **Trust is the product.** Patients don't fear AI drafting; they fear AI *committing them*. Converting "the agent can do everything except sign" from a slogan into a Cedar-forbidden invariant is what makes autonomy acceptable.
- **Enforcement belongs at the action boundary.** Strands' mutable hook ordering (`SDK_FIRST - 1`) lets a policy engine intercept decisions at exactly the moment intent becomes action — cleaner than wrapping every tool.
- **Deterministic beats clever for safety.** Rust + Cedar give reproducible verdicts, sub-second enforcement, and an audit trail an LLM-as-judge could never provide.
- **The law is an API.** ERISA § 503's full-and-fair-review requirements translate directly into policy conditions and legal demands — making the appeal letter simultaneously clinical and procedural.

## What's next

- **Fax/email delivery** to real insurer claims departments and payer-portal connectors.
- **Treating-physician e-signature chain** — a physician counter-signature attestation step.
- **External review escalation** under ACA § 2719 when the first-level appeal is denied.
- **AgentCore Runtime deployment** (ARM64 image ready) and a multi-patient household portal.
- **Broader guideline coverage** — expanding the CMS NCD/LCD database and adding payer-specific policies.

## Built With

strands-agents-sdk, amazon-bedrock, amazon-agentcore, cedar-policy, rust, python, fastapi, pydantic, tailwindcss
