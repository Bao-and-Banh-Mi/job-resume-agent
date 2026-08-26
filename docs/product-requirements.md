# Product Requirements

## 1. Problem statement

Job seekers spend significant time tailoring the same base resume to different job descriptions. Existing AI tools do this quickly but sacrifice factual integrity: they add unearned claims, invented metrics, and phantom leadership. This creates career risk for the applicant and erodes trust with hiring managers. There is room for a tool that speeds up the *legitimate* parts of tailoring — selection, ordering, phrasing — while categorically refusing the illegitimate parts.

## 2. Target user

MVP persona is a technical student or early-career engineer applying to 20–100 roles per season, who:
- has a base resume they trust (e.g., a LaTeX source built from [`templates/resume.template.tex`](../templates/resume.template.tex), optionally with a private, git-ignored overlay such as `.private/alan-resume-source.tex`),
- has more experience/detail than fits on one page,
- has strong feelings about factual accuracy of their resume,
- is comfortable running a local backend and bringing their own LLM account.

Deferred personas: non-technical users, career changers with sparse evidence, users who want cover letters written for them.

## 3. Core user stories

### US-1: Detect a job description
> As a user, when I'm viewing a job posting on LinkedIn / Greenhouse / Lever / Ashby / Workday / a plain-text page, the extension recognizes it and offers *Generate Tailored Resume* without me copy-pasting.

### US-2: Curate an experience bank
> As a user, I can import my base resume (PDF or LaTeX) and edit a structured bank of experiences, projects, skills, and quantified achievements. Each entry has its own evidence field (raw notes, links, artifacts).

### US-3: Generate a tailored draft
> As a user, when I trigger tailoring, the system produces a draft LaTeX resume that fits on one page, selects the most relevant bank entries, and rewrites bullets to align with JD keywords — without adding claims not present in my bank.

### US-4: Review with provenance
> As a user, before I export, I see every bullet next to (a) the evidence it came from, (b) a diff against the original wording, and (c) a flag if the wording is *inferred* rather than a straight quote. I can approve, edit, or reject each bullet.

### US-5: See what's missing
> As a user, I see which JD keywords/skills my bank does not substantiate, so I know what gaps exist and can decide whether to add evidence or move on.

### US-6: Diff against my base
> As a user, I see a full diff between the tailored resume and my base resume, so I understand exactly what changed and why.

### US-7: Export a compiling PDF
> As a user, once I approve, I get a valid ATS-readable PDF and its LaTeX source. The PDF compiles reliably; no manual LaTeX debugging.

### US-8: Bring my own provider account
> As a user, I connect my own OpenAI or Anthropic account (or point at a local Ollama). The system never proxies my prompts through a service the vendor operates.

### US-9: Delete everything, easily
> As a user, one command wipes the local database and any cached provider credentials. My data is mine.

## 4. Acceptance criteria

These are testable and gate v1 (MVP) release. Each maps to a fixture-based test.

### AC-1: Zero-fabrication guarantee
For a fixture set of 20 (JD, bank) pairs where the bank *lacks* a particular JD requirement, the pipeline **must not** emit a bullet claiming that requirement. It must either omit it or list it in the gap report.

**Measurement:** unsupported-claim rate = (# bullets marked unsupported by the evidence linker) / (# bullets shipped). MVP target: **0.0**.

### AC-2: Evidence coverage
Every bullet in the exported PDF resolves to at least one `evidence_id` present in the current experience bank. Enforced at render time; renderer refuses to produce a PDF otherwise.

### AC-3: Inference transparency
Any bullet whose token-level edit distance from its evidence source exceeds a configured threshold (default: > 30% new tokens, or any new numeric token) is flagged `inferred` in the review UI. The user cannot export without acknowledging each `inferred` bullet.

### AC-4: LaTeX validity
For a fixture set of 50 generated drafts, `pdflatex` produces a valid PDF in ≥ 99% of runs within a 30-second sandboxed timeout. Failures produce actionable error messages, not silent skips.

### AC-5: One-page fit
Default template targets one page. If the draft overflows, the review UI shows an *overflow indicator* and offers deterministic shrink strategies (drop lowest-priority bullet, shrink itemsep) rather than silently truncating.

### AC-6: JD detection precision
On a fixture set of 30 real job pages across the supported providers, the extension correctly identifies the JD region in ≥ 95% of pages. False positives on non-JD pages must be ≤ 1% of a browsing corpus of 200 non-JD pages.

### AC-7: Provider egress boundary
Static analysis (a CI check) confirms no code path outside `packages/providers/*` performs outbound HTTP to third-party LLM endpoints. Extension content scripts have no `host_permissions` for LLM providers.

### AC-8: Local delete
`job-resume-agent wipe` removes: SQLite DB, extension local storage (documented steps), OS keychain entries for the app namespace, and any cached PDFs. A smoke test asserts no residual files in the app data directory.

### AC-9: Reference template compiles
`templates/resume.template.tex` compiles under the bundled TeX toolchain in CI. Regression blocks release. (Private overlays such as `.private/alan-resume-source.tex` are git-ignored and not exercised in CI.)

## 5. UX principles

- **Refusal is a first-class outcome.** "I can't back this claim" is a valid, expected state, not an error.
- **Provenance is always one click away.** Every bullet in the review UI expands to show its source evidence.
- **Diffs everywhere.** Original evidence → rewritten bullet. Base resume → tailored resume. Never a blob of new text with no comparison.
- **Approval is per-bullet.** A single "Approve all" button exists but shows a scary confirmation when any bullet is flagged `inferred` or `unsupported`.
- **The user owns the words.** Every field in the review UI is directly editable; the pipeline is a proposal, not an authority.

## 6. Non-goals (v1)

Repeated from [`README.md`](../README.md) for enforcement:

1. No fabrication assist (no "suggest what you might have done").
2. No hosted multi-tenant SaaS.
3. No cover letter generation.
4. No auto-apply / recruiter messaging.
5. No scraping of gated job boards.
6. No server-side storage of provider API keys.
7. No résumé numeric "score."
8. No LinkedIn scraping to seed the bank.
9. No support for résumés outside the bundled LaTeX template family (v1 is one template).
10. No mobile app.

## 7. Success metrics (post-MVP)

Local, opt-in telemetry only (not in v1). When available:

- **Trust metric:** rate at which users export the pipeline's draft without editing any bullet. Higher = more trusted.
- **Refusal rate:** fraction of tailoring runs that surface at least one gap. Expected to be high; low values suggest the model is over-claiming.
- **Time to export:** median seconds from *Generate* to *Export*. Target ≤ 3 min.
- **Compile success rate:** % of drafts that compile on first try.

## 8. Open product questions

Deferred, tracked in [`docs/roadmap.md#open-questions`](roadmap.md#open-questions).
