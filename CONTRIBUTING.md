# Contributing

This project has a strong editorial position, not just a technical one. Please read this document before proposing changes.

## Development principles

### 1. Evidence is a hard constraint, not a soft preference

No bullet reaches a rendered PDF unless it is linked to at least one `evidence_id` in the user's experience bank. This is enforced at the schema layer (see [`docs/data-model.md`](docs/data-model.md)) and re-verified at render time. If you find yourself writing a code path that produces a bullet without provenance, you are writing a bug.

### 2. Rewriting is not the same as inventing

Allowed: changing verbs, reordering clauses, emphasizing keywords that are already substantiated by the evidence.

Not allowed: adding numbers that aren't in the evidence, claiming leadership that isn't in the evidence, generalizing "helped with" into "led," inferring team size, inferring impact.

If the model produces such a bullet, the pipeline must mark the bullet `unsupported` and surface it in the review UI. It must not silently ship.

### 3. Make inference visible

Any rewrite that departs from the evidence's literal wording is flagged as `inferred` in the review UI with a diff against the source evidence. The user must approve inferred wording before export. Do not hide this behind a "trust me" toggle.

### 4. Prefer refusal to hallucination

If the JD requires a skill the bank does not substantiate, the pipeline surfaces it in the *gap list*, not in a bullet. The user then decides whether to (a) add evidence, (b) leave the gap, or (c) abandon the tailoring. Never paper over a gap with plausible-sounding filler.

### 5. Local-first, provider-agnostic

Do not couple the tailoring logic to a specific LLM provider. All LLM calls go through the provider adapter interface (see [`docs/technical-architecture.md#provider-adapters`](docs/technical-architecture.md)). If a feature only works with one provider (e.g., structured outputs via a specific API), gate it behind a capability check on the adapter, do not hard-code it.

### 6. Privacy is a design constraint, not a compliance checklist

Assume the experience bank contains personally identifiable information, unpublished work, and NDA-adjacent details. Design so that:
- No PII leaves the machine except in the LLM call the user explicitly triggered, to the provider the user configured.
- The extension's content script never sends page content to a third party we operate.
- Telemetry is off by default and, if it ever exists, is anonymous and opt-in.

See [`docs/security-and-privacy.md`](docs/security-and-privacy.md) for the full threat model.

### 7. LaTeX correctness is table stakes

A tailored resume that does not compile is a critical bug. The renderer validates the LaTeX AST before invoking `pdflatex`, and PDF builds run in a sandbox with a timeout. Renderer regressions block release.

## Coding standards

- **Backend:** Python 3.11+, FastAPI, Pydantic v2 for schemas, `ruff` + `mypy --strict` in CI.
- **Frontend:** TypeScript strict mode, React 18, Zod for runtime validation. No `any` without a `// justified:` comment.
- **Extension:** Manifest V3. Minimum permissions (see [`docs/security-and-privacy.md#extension-permissions`](docs/security-and-privacy.md)). No remote code loading.
- **Tests:** Every tailoring change ships with a fixture-based regression test — a JD, the bank, and the expected evidence matrix. Snapshot tests for LaTeX output.

## Reviewing model output during development

When you're iterating on prompts or the retrieval layer, run the evaluation harness (Phase M2) against the fixture set before opening a PR. A PR that improves keyword coverage but regresses evidence coverage or increases the unsupported-bullet rate will not be merged.

## PR checklist

- [ ] Schema changes have a migration and a fixture update.
- [ ] Any new LLM call goes through the provider adapter, not the provider SDK directly.
- [ ] Any new user-facing text that could be model-generated is routed through the review UI's inference-flag path.
- [ ] Security-sensitive changes (permissions, key storage, network egress) are called out in the PR description and reviewed by a second person.
- [ ] The reference template `templates/resume.template.tex` still compiles under the LaTeX pipeline (and, if you have it locally, `.private/alan-resume-source.tex` still compiles too).

## What not to build

Refer to the non-goals in [`README.md`](README.md#non-goals-v1) and [`docs/product-requirements.md`](docs/product-requirements.md). If you think a non-goal should change, open an ADR before writing code.
