# Video Script — ClaimGuard (3 minutes)

**Title:** ClaimGuard: The Autonomous Patient Advocate That Fights Algorithmic Insurance Denials
**Length:** 3:00 · **Format:** screen capture + VO — patient portal (localhost:8080) + terminal
**Brand:** Deep Obsidian Navy (#0B0F19) · Trust Cobalt Blue (#2563EB) · Healing Teal (#0D9488)

---

## [0:00 – 0:35] The Hook — The Denial Machine

**VISUAL:** A physical denial letter on a kitchen table next to medical bills. Slow push-in on the words *"your claim has been denied."* Cut to the portal hero: obsidian navy background, ClaimWard logo in navbar.

**VO (warm, steady — a neighbor, not a narrator):**

> "After careful review, your claim has been denied." Twelve words that arrive for forty-nine million Americans every year — some written by an algorithm in 1.2 seconds, reviewed by no physician.
>
> Over 220 billion dollars in medical debt is crushing families right now. And here's the part that should make you angry: 99.8% of patients never appeal — even though sixty to ninety percent of appeals *win*.
>
> Why? Because a winning appeal is a legal document. ERISA citations. CMS clinical criteria. A 180-day deadline. Who can fight that while they're sick?
>
> So we built them a fighter.

**ON SCREEN:** "$220B debt · 49M denials/yr · 99.8% unappealed · 60–90% win on appeal" metric cards.

---

## [0:35 – 1:30] Live Portal Demo — Denial to Drafted Appeal

**VISUAL:** Portal. Cursor clicks **"Sample 1: Cigna Lumbar MRI Denial ($4,850)"**. The 5-stage timeline lights up cobalt as each stage completes.

**VO:**

> Meet ClaimGuard. Sarah Jenkins — Cigna denied her $4,850 lumbar MRI. PxDx's stated reason: "no documented 6 weeks of conservative therapy."
>
> Watch the agent work. Stage one: it parses the letter — CPT 72148, diagnosis M54.51, billed amount, and the ERISA deadline. Stage two: it queries the CMS LCD guidelines and finds the exact criteria — including the exception Cigna's denial ignored: *progressive motor weakness waives the conservative-therapy requirement*.
>
> Sarah has exactly that. Eight weeks of failed physical therapy — documented — plus 4/5 motor weakness in her left foot.
>
> Stage three: ClaimGuard drafts the formal appeal. Two pages, statutory form — citing ERISA, 29 U.S.C. § 1133, demanding Cigna hand over its reviewer's credentials under 29 C.F.R. § 2560.503-1.

**ON SCREEN:** timeline steps [1→2→3] turning teal; letter preview scrolling with statutory headings.

---

## [1:30 – 2:15] The Cedar HITL Block — Nothing Submits Without the Patient

**VISUAL:** Focus on Stage 4. The Patient Review & Sign card. Then Evidence Vault panel.

**VO:**

> Here's the rule that makes this trustworthy: the agent cannot submit. Ever. Not "shouldn't" — *cannot*.
>
> Every tool call passes through a zero-trust gateway — a Rust scanner plus Cedar policies hooked into the Strands SDK *before* any tool runs. If the patient hasn't signed, Cedar says no, and there is no tool call at all.
>
> Watch the Evidence Vault: attempt to submit unsigned — **DENY** — with the SHA-256 hash of the exact arguments logged. Try to slip an unredacted Social Security Number through any tool call — **DENY**. The HIPAA gate doesn't negotiate.
>
> And the signature isn't a rubber stamp. Signing generates a SHA-256 token bound to *this exact letter* — approving one appeal can never authorize a different one.

**ON SCREEN:** Evidence Vault rows: DENY `deny_submit_unsigned` + args hash; DENY `phi_unredacted`.

---

## [2:15 – 2:40] The Patient Signs — Submitted

**VISUAL:** The sign card. Full appeal letter. Patient clicks **"Review & Cryptographically Sign Appeal"**. Button transitions to teal; Stage 5 turns done; evidence log gains an ALLOW row.

**VO:**

> Sarah reads the appeal. It's *her* words, her doctor's facts, with the law behind them. She signs.
>
> A cryptographic token is issued — SHA-256. Cedar flips to ALLOW. The appeal is submitted to Cigna under ERISA § 503, with its cryptographic attestation attached.
>
> One minute of agent work instead of an evening of despair — and the human being always holds the last word.

---

## [2:40 – 3:00] Architecture & AWS Stack

**VISUAL:** Architecture diagram, then terminal: `pytest -v` scrolling green, ending in the pass summary. End card: ClaimWard logo, tagline, repo URL.

**VO:**

> Under the hood: a Strands Agents SDK agent on Amazon Bedrock Nova Micro, running in an AWS AgentCore-ready container. Cedar policies intercept every tool call through the SDK's hook system — the Rust `zn` gateway scans first, Cedar judges, and every verdict lands in a SHA-256 evidence vault.
>
> Full automated test suite: all green — policy matrix and end-to-end cycles, no cloud credentials needed.
>
> ClaimGuard: research the guidelines. Draft the appeal. **But never sign — that right belongs to the patient.**

**ON SCREEN:** "Strands Agents SDK · Amazon Bedrock · Cedar · AgentCore" · repo link.

---

## Production Notes

- Hold the denial letter full-screen ≥3 s (it's the emotional anchor).
- The Evidence Vault DENY/ALLOW rows are the trust payoff — keep each ≥3 s on screen.
- VO pace ~150 wpm; if the portal demo runs long, trim the letter scroll, never the sign beat.
- End card URL: github.com/tljohnsilver/claimward.
