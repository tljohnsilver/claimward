// ClaimWard Cedar Policies — Zero-Trust Patient Advocacy Gate
// Protects patients against unauthorized appeal submissions and HIPAA privacy leaks.

// 1. Permit non-destructive clinical analysis and appeal drafting tools
@id("permit_research_draft")
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

// 2. Strict Patient Gate: forbid final appeal submission unless explicitly approved & signed by patient
// NOTE: appeal state (human_signed, days_until_deadline) flows via context —
// the installed cedarpy build cannot deserialize attribute-bearing entities.
@id("deny_submit_unsigned")
forbid(
    principal,
    action == Action::"submit_appeal_package",
    resource
)
unless {
    context.human_signed == true &&
    context.days_until_deadline >= 0
};

// 3. Explicit complement: signed appeals within the ERISA deadline may be submitted
@id("permit_signed_submit")
permit(
    principal,
    action == Action::"submit_appeal_package",
    resource
) when {
    context.human_signed == true &&
    context.days_until_deadline >= 0
};

// 4. HIPAA Gate: forbid transmitting unredacted patient Social Security Numbers or unmasked identifiers
@id("deny_phi_unredacted")
forbid(
    principal,
    action,
    resource
) when {
    context.phi_unredacted == true
};
