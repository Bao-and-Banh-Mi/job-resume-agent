# Roadmap

Phased build plan. Each phase is scoped to a small number of clearly testable outcomes. Ship-worthiness of a phase is gated by explicit exit criteria, not calendar dates.

## Phase M0 — Design freeze (this repo, today)

**Goal:** enough documentation that any competent engineer can start Phase M1 without re-inviting the product debate.

**Deliverables** (all present):
- README, CONTRIBUTING, product requirements, technical architecture, data model, security & privacy, this roadmap, ADR-001, example experience bank.

**Exit criteria:**
- Non-goals list is stable.
- Acceptance criteria (`product-requirements.md#4`) are enumerated and testable.
- Data model has type-level closure — no dangling references, no unresolved TODOs in the schema.

## Phase M1 — Backend skeleton + local bank CRUD

**Goal:** you can start the backend, put your bank in, edit it, and export it. No LLM involvement yet.

**In scope:**
- FastAPI app on `127.0.0.1`, loopback TLS, per-install cert, bearer token.
- SQLite + Alembic migrations for the schemas in [`data-model.md`](data-model.md).
- CRUD APIs for bank/entries/bullets/evidence/skills, with schema-enforced invariants (bullets require evidence).
- Import from LaTeX (parser for the reference template family) and from PDF (best-effort with review modal).
- Export bank to YAML matching [`example-experience-bank.yaml`](example-experience-bank.yaml).
- `wipe` command.
- Minimal React web UI for bank editing (no review pane yet).

**Exit criteria:**
- Import a filled-in copy of `templates/resume.template.tex` (e.g., the maintainer's local `.private/alan-resume-source.tex`) → bank with correct entries → export YAML → diff against a hand-verified target ≤ trivial whitespace.
- `wipe` leaves no residual files or keychain entries (smoke test passes).

## Phase M2 — Tailoring pipeline with NullAdapter + evidence linker

**Goal:** the full tailoring pipeline runs end-to-end using a deterministic fake model. The evidence linker is the star of this phase.

**In scope:**
- Provider adapter interface (see [`technical-architecture.md#3-provider-adapter-interface`](technical-architecture.md#3-provider-adapter-interface)).
- `NullAdapter` returning canned candidate bullets from fixtures.
- `KeywordAnalyzer`, `Retriever` (BM25 baseline), `Tailor` (fake), `EvidenceLinker`.
- Draft persistence + Review UI (bullet inspector, coverage panel, gap panel, per-bullet approve).
- Fixture regression harness: 20 (JD, bank) pairs with expected outputs.

**Exit criteria (map to acceptance criteria):**
- **AC-1 (zero fabrication):** all 20 fixtures — unsupported-bullet rate = 0 at export.
- **AC-3 (inference transparency):** every fixture bullet with a rephrase classifies correctly across `verbatim / paraphrased / inferred`.
- Property-based tests on the linker pass (no bullet with new numeric tokens escapes `unsupported`).

## Phase M3 — LaTeX renderer + PDF pipeline + real provider (OpenAI or Anthropic)

**Goal:** you can generate an actual tailored PDF using your own OpenAI or Anthropic account.

**In scope:**
- LaTeX AST validator + template binder (see [`technical-architecture.md#6-latex-validation-strategy`](technical-architecture.md#6-latex-validation-strategy)).
- `pdflatex` sandbox (per-request tmpdir, `-no-shell-escape`, timeouts, OS sandboxing where available).
- Post-compile validation (page count, text extract, embedded fonts).
- `OpenAIAdapter` + `AnthropicAdapter` with OS keychain integration for the API key.
- CI enforces provider-import boundary (no provider SDKs outside `packages/providers/*`).

**Exit criteria:**
- **AC-4 (LaTeX validity):** ≥ 99% compile rate on 50 fixture drafts.
- **AC-5 (one-page fit):** overflow indicator works; deterministic shrink offered.
- **AC-9:** reference template still compiles in CI.
- End-to-end run using a real provider produces a compiling PDF from the Alan bank against a real JD sample.

## Phase M4 — Chrome extension + full flow

**Goal:** click the button in the browser and get a review-ready draft, without touching the terminal.

**In scope:**
- MV3 extension with per-site JD extractors (LinkedIn, Greenhouse, Lever, Ashby, Workday) + generic fallback.
- Cert pinning + bearer token issuance on first-run.
- Side panel UI + hand-off to backend web review UI.
- Documented Chrome Web Store review notes for the permissions rationale.

**Exit criteria:**
- **AC-6 (JD detection):** ≥ 95% precision on 30 real JD pages; ≤ 1% false positive on 200 non-JD pages.
- **AC-7 (egress boundary):** static analysis passes; extension has no LLM-provider host permissions.

## Phase M5 — Optional: BYO OAuth for providers that expose it; multi-template; local retrieval quality

**Goal:** breadth once depth is done.

**In scope (any/all as appetite allows):**
- Provider OAuth flow for any provider that ships user-scoped locally-installable auth by then (see [`security-and-privacy.md#6`](security-and-privacy.md#6-provider-oauth-vs-byo-key-design-decision)).
- Second and third LaTeX templates with the same evidence guarantees.
- Optional Ollama-backed embedding rerank for retrieval quality without egress.
- Cover letters — **only** if the evidence-linker guarantee can be extended without slippage; explicit ADR required before starting.

**Exit criteria:** per feature.

## Phase M6 — (much later) Multi-user cloud sync

Explicitly *not* in v1 (see non-goals). A separate design pass; not roadmapped in detail here. Any move away from local-first requires a new ADR superseding ADR-001.

---

## Cross-cutting workstreams

Run in parallel with the phases above:

- **Fixtures and evals** — expand the (JD, bank) fixture set every phase. Track unsupported-bullet rate, evidence coverage, inferred rate, coverage ratio.
- **Prompt hygiene** — the Tailor prompt is source-controlled and versioned. Prompt changes ship with fixture deltas so we see regressions.
- **Docs** — every user-facing change updates PRD/AC; every architectural change gets an ADR.

## Open questions

Explicitly deferred; do not block M1.

1. **Rerank without egress.** Retrieval quality with BM25 alone may be marginal on small banks; a local embedding backend (Ollama, sentence-transformers) would help but adds install friction. Revisit at M5.
2. **Multi-template design.** How to encode the "template allowlist of commands" so multi-template does not multiply the LaTeX validator surface. Likely a small template manifest.
3. **PDF import fidelity.** Extracting bullets from a PDF resume is lossy. Do we require LaTeX/YAML import for M1 and treat PDF as advisory? Current answer: yes.
4. **Extension: Firefox/Safari.** Deferred until MV3 parity settles. Not a v1 blocker.
5. **Recruiter-facing evidence share.** Could this tool expose a *view-only, per-bullet-provenance* link for recruiters who want to verify? Interesting; explicitly out of scope until v2.
6. **Cover letter question.** If we ever build one, the same evidence-first constraints must apply, which is harder because cover letters lean on narrative. Requires an ADR.
7. **JD staleness.** Job listings move/delete. Do we snapshot the JD HTML for later reference? Storage/PII tradeoff. Current stance: keep raw text + URL, not HTML.
8. **Model choice defaults.** The Tailor benefits from strong instruction-following. Do we ship a recommended-model note per provider, or stay silent? Leaning: recommend, don't require.
9. **Bank versioning UX.** When a bank change invalidates existing drafts, what's the right prompt — "regenerate," "diff-merge," or just show the warning? Needs UX prototyping in M2.
