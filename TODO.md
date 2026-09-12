# ClaimWard: Implementation Roadmap & Execution Checklist (TODO.md)

**Target Directory:** `/home/ubuntu/claimguard`  
**Engineer:** GLM 5.3-Flash (OpenCode)  
**Master Architect:** Antigravity  
**Goal:** Build and verify ClaimWard with 100% passing tests, beautiful UI, and complete Devpost submission package.

---

## Phase 1: Environment & Sample Data Setup
- [ ] Create `.gitignore` (ignore `__pycache__`, `venv`, `*.pyc`, `data/evidence/*.jsonl`).
- [ ] Populate `data/sample_denials/denial_01_mri_lumbar.json` (Cigna PxDx denial of CPT 72148, $4,850).
- [ ] Populate `data/sample_denials/denial_02_biologic_humira.json` (UnitedHealth step therapy denial for Crohn's / arthritis, $18,500).
- [ ] Populate `data/sample_denials/denial_03_colonoscopy_oop.json` (Preventive screening miscoded, $2,850).
- [ ] Populate `data/clinical_criteria/ncd_lcd_guidelines.json` with standard medical necessity guidelines for common procedures.

---

## Phase 2: Core Models & Cedar Policies
- [ ] Create `src/models.py`:
  - Pydantic models: `DenialInfo`, `ClinicalGuideline`, `AppealPackage`, `HITLApprovalCard`, `AuditEvent`.
- [ ] Create `src/policies/policies.cedar`:
  - Cedar policies enforcing:
    1. Unsigned appeals CANNOT be submitted (`submit_appeal_package` requires `resource.human_signed == true`).
    2. Overdue appeals (> 180 days past ERISA deadline) are flagged.
    3. Unredacted PHI (SSN) is strictly blocked.
- [ ] Create `src/policies.py`:
  - Python wrapper over `cedarpy` evaluating policies deterministically.
- [ ] Create `tests/test_cedar_policies.py` and verify with `pytest`.

---

## Phase 3: Strands SDK Agent & Safety Gateway
- [ ] Create `src/tools.py`:
  - Strands `@tool` functions:
    1. `parse_denial_letter(raw_text: str)`
    2. `query_clinical_criteria(cpt_code: str, diagnosis: str)`
    3. `draft_erisa_appeal(denial_json: str, clinical_evidence: str, patient_notes: str)`
    4. `request_patient_signature(appeal_id: str, appeal_draft: str)`
    5. `submit_appeal_package(appeal_id: str, recipient: str, signature_token: str)`
- [ ] Create `src/gateway.py`:
  - Strands Hook (`ClaimWardGatewayHook`) inheriting from `Hook` or wrapping `BeforeToolCallEvent` / `AfterToolCallEvent` (Order: `SDK_FIRST - 1`).
  - Intercepts calls, validates against Cedar and Rust `zn analyze`, appends to SHA-256 evidence vault.
- [ ] Create `src/hitl.py`:
  - Manages pending patient approvals, validates cryptographic SHA-256 tokens.
- [ ] Create `src/agent.py`:
  - Factory `build_claimguard_agent()` using `strands.Agent`, `BedrockModel(model_id="us.amazon.nova-micro-v1:0")`, and tools.
- [ ] Create `tests/test_agent_workflow.py` and verify.

---

## Phase 4: Patient Advocate Web Portal (FastAPI)
- [ ] Create `src/dashboard.py`:
  - FastAPI app serving:
    - `GET /` -> Patient Portal UI
    - `POST /api/denials/upload` -> Ingest denial text/file and trigger agent
    - `GET /api/appeals` -> List appeals and current status
    - `POST /api/appeals/{id}/sign` -> Patient approves and signs appeal (HITL action)
    - `GET /api/evidence` -> Immutable audit trail
- [ ] Create `src/static/index.html`:
  - Clean, empathetic, high-contrast UI designed for stressed patients:
    - Hero section with live debt rescued counter ($ rescued, % overturned).
    - Upload Denial Letter box (drag-and-drop or sample buttons: "Cigna Lumbar MRI Denial", "UnitedHealth Humira Denial").
    - Real-time agent processing visualizer (Extracting codes -> Searching CMS guidelines -> Drafting ERISA appeal).
    - Patient Review & Sign Card (One-click cryptographic sign & submit).
    - Evidence Vault log.

---

## Phase 5: Hackathon Submission Artifacts
- [ ] Create `README.md`:
  - Empathy-first presentation of ClaimWard, the $220B medical debt problem, ProPublica investigative context, architecture diagram, tech stack, and quickstart.
- [ ] Create `DEVPOST_SUBMISSION.md`:
  - Full Devpost form fields: Tagline, Inspiration, What it does, How we built it, Challenges, Accomplishments, What we learned, What's next.
- [ ] Create `VIDEO_SCRIPT.md`:
  - 3-minute video recording script with exact second-by-second timestamps and screen actions.
- [ ] Create `BUILDER_AWS_ARTICLE.md`:
  - Technical article ready for AWS Builder Community.

---

## Phase 6: Full Verification & Remote Push
- [ ] Run full test suite: `/home/ubuntu/.local/bin/pytest -v tests/` (All tests must pass).
- [ ] Test FastAPI portal with demo cycle.
- [ ] Commit and push to `origin/main` (`git@github-claimward:tljohnsilver/claimward.git`).
