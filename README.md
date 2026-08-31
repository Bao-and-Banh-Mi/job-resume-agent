# job-resume-agent

An **evidence-grounded** resume tailoring system. Given a job description detected in the browser and a structured *experience bank* the user has curated, it produces an ATS-readable LaTeX/PDF resume where **every bullet is traceable to a piece of user-provided evidence**. Any wording the model inferred, generalized, or reworded is visibly flagged and must be approved by the user before export.

The product refuses to fabricate. If a required skill or achievement is not backed by evidence, it says so instead of inventing one.

> **Status: working proof of concept.** The repository includes an MCP server,
> evidence linker, safe LaTeX renderer, CLI, and 65 tests. It does not yet
> include the Chrome extension.

## How it works: the model judges, the server enforces

There is no keyword extractor in this project, by design. An MCP server is
*called by* a language model, so the reasoning should happen in the model —
which can tell that "Redis, Kafka, DynamoDB, low-latency" means distributed
systems, and that "barista-made espresso" is a perk, not a requirement. A
token matcher can do neither, and an earlier version of this repo proved it:
it read a Verkada posting as having 40 "requirements", 17 of which were
hyphenated boilerplate like `well-being` and `team-building`. Coverage
numbers computed against that denominator were meaningless.

So the split is:

| The calling LLM decides | The server enforces |
|---|---|
| Which requirements the posting actually states | That cited `bullet_id`s exist in the bank |
| Which experience speaks to them | That coverage claims have surviving citations |
| What order content appears in | That rephrasings introduce no new numbers or proper nouns |
| How a bullet is worded for this posting | That the PDF really is one page (by compiling it) |
| | That Education and Skills are always present |

The model gets full latitude over **selection and wording**, and zero
latitude over **facts**. That is what makes "let the model polish it" safe.

## MCP tool workflow

1. **`load_bank(path)`** — returns the **full bank catalog**: every entry,
   every bullet, every `bullet_id`. The agent reads this; it is the only
   source of resume content.
2. **`set_job_description(raw_text, ...)`** — accepts raw scraped HTML and
   returns clean plain text plus a `job_id`. It deliberately does *not*
   extract requirements — that is the agent's job.
3. **`analyze_fit(requirements, job_id)`** — the agent submits the
   requirements it found and the `bullet_id`s/skills backing each verdict.
   The server validates: unresolvable citations are stripped, and any
   `covered`/`partial` verdict left with no evidence is **downgraded to a
   gap** and reported in `corrections`. Returns flat coverage,
   must-have-weighted coverage, and a recommendation.
4. **`tailor_resume(selection, job_id)`** — the agent picks entries, bullets,
   and order. Optional `rewritten_text` per bullet is classified by the
   evidence linker; new numbers or new proper nouns make it `unsupported`
   and block export. Unknown ids are errors, not silent skips.
5. **`get_draft(draft_id)`** — retrieve a draft.
6. **`export_draft(draft_id, output_dir)`** — renders `.tex` and **compiles
   with `pdflatex`**, counting real pages. On overflow the least-important
   trailing bullets are dropped (never reworded) and it recompiles. Returns
   `page_count`, `pdf_path`, and `dropped_bullet_ids`.

### What the guarantees look like in practice

Validated against five real 2027 internship postings (GlossGenius, Verkada
×2, Compeer, BTI360) using a real experience bank:

- All five export to genuine one-page PDFs with Education and Skills present.
- Verkada Mobile correctly reports 3 must-have gaps (Swift, Kotlin, mobile
  architecture) and refuses to claim them — the bank has no iOS evidence.
- An agent asserting `verdict: "covered"` for Swift with no citation gets
  coverage `0.0` and an explicit correction.
- An agent rewriting a bullet to "Shipped a SwiftUI iOS app to 50,000 users"
  gets `unsupported`, and `export_draft` refuses.
- Inflating a real metric (`50+` → `500+`) is caught the same way.
- `accept_inferred: true` cannot launder an `unsupported` bullet.

## Quickstart

Requires Python 3.11+ and a TeX distribution with `pdflatex` on `PATH`
(MiKTeX, TeX Live) for the one-page gate. Without `pdflatex`, exports still
work but skip page-count enforcement (a warning is returned).

```bash
python -m pip install -e ".[dev]"

# Inspect the bank the way an agent sees it (bullet_ids and all)
resume-agent catalog --bank docs/example-experience-bank.yaml

# Apply a selection JSON (normally authored by the agent) and compile
resume-agent tailor --bank docs/example-experience-bank.yaml \
  --jd path/to/job.txt --selection selection.json --export --out ./out
```

Run the MCP server over stdio:

```bash
resume-agent serve
```

Register it with Claude Code:

```bash
claude mcp add resume-agent -- resume-agent serve
```

Set `RESUME_AGENT_BANK_PATH` to a local bank with your own information. Keep
your private bank and outputs under `.private/` — that directory is
git-ignored. The committed example bank uses placeholder contact details and
is safe to publish.

---

## Why this exists

Most "AI resume tailoring" tools optimize for keyword match and paragraph fluency at the cost of factual integrity. They will happily add "led a team of 10" or "improved latency by 40%" when the user never claimed either. That is a career risk for the user and a trust problem for the recipient.

This project takes the opposite stance: the model is a **selector and rephraser over the user's own evidence**, not a generator of achievements. Tailoring means *selecting, reordering, and rephrasing* — never *inventing*. Crucially, that constraint is enforced mechanically by the server rather than requested politely in a prompt. See [`docs/product-requirements.md`](docs/product-requirements.md) for the acceptance criteria that operationalize this.

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

## Repository layout

```
job-resume-agent/
├── src/resume_agent/
│   ├── mcp_server.py             # the six MCP tools; agent-facing contract
│   ├── catalog.py                # renders the bank for the agent to read
│   ├── jd_clean.py               # HTML -> clean posting text
│   ├── fit.py                    # validates the agent's coverage claims
│   ├── tailor.py                 # assembles a draft from the agent's selection
│   ├── evidence_linker.py        # classifies rephrasings against evidence
│   ├── latex_renderer.py         # safe LaTeX rendering (escaping, sections)
│   ├── export.py                 # export gate + real pdflatex one-page loop
│   ├── models.py                 # Pydantic schemas
│   ├── state.py                  # process-local session store
│   └── cli.py                    # serve / catalog / tailor
├── templates/resume.template.tex # public, PII-free reference template
├── tests/                        # 65 tests, incl. adversarial fabrication tests
├── docs/
└── .private/                     # git-ignored: real bank, resumes, outputs
```

The Chrome extension is not built yet; the MCP tool boundary is designed so
it can call the same tools the agent does.

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
