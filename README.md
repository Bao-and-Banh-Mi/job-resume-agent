# job-resume-agent

An **evidence-grounded** resume tailoring system. Given a job description detected in the browser and a structured *experience bank* the user has curated, it produces an ATS-readable LaTeX/PDF resume where **every bullet is traceable to a piece of user-provided evidence**. Any wording the model inferred, generalized, or reworded is visibly flagged and must be approved by the user before export.

The product refuses to fabricate. If a required skill or achievement is not backed by evidence, it says so instead of inventing one.

> **Status: proof of concept.** The repository includes a deterministic MCP server, evidence linker, safe LaTeX renderer, CLI, and tests. It does not yet include the Chrome extension or external LLM provider adapters.

## MCP tool workflow

The MCP server exposes five tools. **`match_skills` is the primary tool** — call it
first, before generating anything:

1. **`load_bank(path)`** — load an experience bank YAML.
2. **`set_job_description(raw_text, ...)`** — capture a JD, extract requirements.
3. **`match_skills(job_id)`** — *(primary)* pure analysis: which JD requirements the
   bank supports (with `evidence_ids`/`bullet_ids`/`skill_names`), which are gaps,
   and a `coverage_ratio`. Creates no draft, rewrites nothing. Use this to decide
   whether the bank has enough evidence for a role before tailoring at all.
4. **`tailor_resume(job_id)`** — *(intentionally minimal)* builds a `Draft` from
   only the entries/bullets/skills that actually matched a JD keyword. Bullet text
   is always copied **verbatim** from the bank — selection only, never rewriting or
   padding. Entries and skill groups with zero matches are dropped rather than
   included as filler.
5. **`get_draft(draft_id)`** — retrieve a previously tailored draft.
6. **`export_draft(draft_id, output_dir)`** — render the draft to `.tex` **and
   compile it with `pdflatex`** to enforce a real one-page result. If the compiled
   PDF is more than one page, the single lowest-`match_score` bullet is dropped
   (pure removal, never reworded) and it recompiles, repeating until it fits one
   page or bullets run out. The response reports `page_count` and
   `dropped_bullet_ids` so you can see exactly what was cut. If it still can't fit
   after trimming, export fails rather than shipping an overflowing PDF.

## Quickstart

Requires Python 3.11+ and a TeX distribution with `pdflatex` on `PATH` (MiKTeX,
TeX Live, etc.) for the one-page export gate. Without `pdflatex`, exports still
work but skip the page-count enforcement (a warning is returned).

```bash
python -m pip install -e ".[dev]"
resume-agent tailor --bank docs/example-experience-bank.yaml --jd path/to/job-description.txt --json
resume-agent tailor --bank docs/example-experience-bank.yaml --jd path/to/job-description.txt --export --out ./out
```

To run the MCP server over stdio:

```bash
resume-agent serve
```

For private use, point `RESUME_AGENT_BANK_PATH` at a local bank containing your own information. Keep the filled resume and private bank under `.private/`; that directory is ignored by Git. The committed example bank uses placeholder contact information and is safe to publish.

---

## Why this exists

Most "AI resume tailoring" tools optimize for keyword match and paragraph fluency at the cost of factual integrity. They will happily add "led a team of 10" or "improved latency by 40%" when the user never claimed either. That is a career risk for the user and a trust problem for the recipient.

This project takes the opposite stance: the model is a **retriever and rewriter over the user's own evidence**, not a generator of achievements. Tailoring means *selecting, reordering, and rephrasing* — never *inventing*. See [`docs/product-requirements.md`](docs/product-requirements.md) for the acceptance criteria that operationalize this.

## Product shape

Three components, loosely coupled:

1. **Chrome extension.** Detects when the active tab is a job description on a supported site (LinkedIn, Greenhouse, Lever, Ashby, Workday, plain text). Offers a *Generate Tailored Resume* action. Sends the JD to the local backend; opens a review UI when the draft is ready.
2. **Local backend + web app.** Owns the experience bank, the tailoring pipeline, the evidence matrix, and the LaTeX/PDF renderer. Runs on `localhost` by default. Ships a review UI: side-by-side diff vs. base resume, evidence links per bullet, keyword coverage heatmap, unsupported-claim warnings, approve/reject/edit per bullet.
3. **Provider adapters (BYO account).** The user connects their own OpenAI, Anthropic, or local (Ollama) account. We do not proxy through our servers and, in local-first mode, we do not store provider keys in a hosted DB — see [`docs/security-and-privacy.md`](docs/security-and-privacy.md).

The public reference LaTeX template lives at [`templates/resume.template.tex`](templates/resume.template.tex) and is used as the visual/structural target for the renderer. Personal identifiers (name, email, links, phone, citizenship) are declared as macros in the template so they can be overridden by a private overlay. The maintainer's own resume source, which contains real PII, lives at `.private/alan-resume-source.tex` and is git-ignored — treat it as the canonical worked example of what a filled-in template looks like, not as a file that ships with the repository. A minimal experience bank derived from that private source is at [`docs/example-experience-bank.yaml`](docs/example-experience-bank.yaml).

## Non-goals (v1)

- **No fabrication assist.** No "suggest a bullet you might have done." No "fill in a plausible metric."
- **No hosted multi-tenant SaaS.** MVP is local-first. Cloud sync is deferred (see roadmap).
- **No auto-apply.** We do not submit applications, message recruiters, or write cover letters. Out of scope.
- **No scraping of gated job boards.** The extension reads the *currently open* page in the user's own browser session; it does not crawl.
- **No storage of provider API keys server-side in v1.** Keys live in OS keychain or extension local storage.
- **No résumé "score."** Numeric ATS scores are pseudoscience without the ATS in the loop. We show keyword coverage and evidence coverage, not a grade.
- **No LinkedIn scraping to seed the experience bank.** Import is manual or from user-uploaded PDF/LaTeX only.

## Documentation map

| File | Purpose |
|---|---|
| [`docs/product-requirements.md`](docs/product-requirements.md) | User stories, acceptance criteria, non-goals, UX principles |
| [`docs/technical-architecture.md`](docs/technical-architecture.md) | System diagram, components, provider adapter interface, LaTeX validation |
| [`docs/data-model.md`](docs/data-model.md) | Experience bank schema, evidence links, tailored-resume artifact schema |
| [`docs/security-and-privacy.md`](docs/security-and-privacy.md) | Threat model, extension permissions rationale, key storage, data flows |
| [`docs/roadmap.md`](docs/roadmap.md) | Phased build plan from M0 (skeleton) through M5 (multi-user cloud) |
| [`docs/adr/001-local-first-provider-agnostic.md`](docs/adr/001-local-first-provider-agnostic.md) | Foundational architecture decision record |
| [`docs/example-experience-bank.yaml`](docs/example-experience-bank.yaml) | Sample bank derived **only** from the maintainer's private `.private/alan-resume-source.tex` |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Development principles, coding standards, review posture |

## Repository layout (target)

```
job-resume-agent/
├── templates/
│   └── resume.template.tex       # public, PII-free reference LaTeX template
├── .private/                     # git-ignored; maintainer's real resume source lives here
├── README.md
├── CONTRIBUTING.md
├── docs/                         # (this repo, today)
├── apps/
│   ├── extension/                # Chrome MV3 extension (TS)
│   ├── backend/                  # FastAPI (Python) + SQLite
│   └── web/                      # React review UI
├── packages/
│   ├── providers/                # provider adapter interface + impls
│   ├── tailoring/                # retrieval, rewrite, evidence-matrix builder
│   ├── latex/                    # renderer, validator, PDF pipeline
│   └── schema/                   # shared Zod/Pydantic schemas
└── tests/
    └── fixtures/                 # JD samples, expected evidence matrices
```

Only `templates/resume.template.tex`, `README.md`, `CONTRIBUTING.md`, and `docs/` exist today in the tracked tree. `.private/` is present in the maintainer's local checkout but is git-ignored and does not ship. The rest is the target of Phase M1 (see roadmap).

## Assumptions on record

These are the reasonable assumptions this design makes without asking the user. Change them by opening an ADR.

1. **Local-first, single-user MVP.** Cloud/multi-user is a v2 concern. See [`docs/adr/001-local-first-provider-agnostic.md`](docs/adr/001-local-first-provider-agnostic.md).
2. **BYO provider account.** We do not front an LLM as a service. The user picks OpenAI, Anthropic, or Ollama; we call it with their credentials.
3. **LaTeX is the source of truth for the tailored artifact.** PDF is a build product. The user's base template (`templates/resume.template.tex`, optionally overlaid by a private file such as `.private/alan-resume-source.tex`) defines the layout envelope.
4. **Python backend, TypeScript extension + web UI.** Matches the ML/LaTeX ecosystem on the backend and the browser platform on the frontend.
5. **Chrome first.** Firefox/Safari can follow via MV3 compatibility once the surface is stable.
6. **The bank is user-owned.** The user can export the full bank as YAML at any time and delete the local DB with one command.
7. **Every generated bullet carries provenance.** No bullet reaches the PDF without at least one `evidence_id` reference in the tailored-resume artifact.

## Open questions

Tracked in [`docs/roadmap.md#open-questions`](docs/roadmap.md#open-questions).
