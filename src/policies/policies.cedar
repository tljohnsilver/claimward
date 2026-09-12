// ClaimGuard Cedar Policies — Zero-Trust Patient Advocacy Gate
// Protects patients against unauthorized appeal submissions and HIPAA privacy leaks.

// 1. Permit non-destructive clinical analysis and appeal drafting tools
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
forbid(
    principal,
    action == Action::"submit_appeal_package",
    resource
)
unless {
    resource.human_signed == true &&
    resource.days_until_deadline >= 0
};

// 3. HIPAA Gate: forbid transmitting unredacted patient Social Security Numbers or unmasked identifiers
forbid(
    principal,
    action,
    resource
)
when {
    context.phi_unredacted == true
};
