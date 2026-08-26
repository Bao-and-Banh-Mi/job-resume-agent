# Technical Architecture

## 1. System overview

```
┌────────────────────────────┐        ┌──────────────────────────────┐
│  Chrome Extension (MV3)    │        │  User's browser tab (JD page) │
│  ─────────────────────     │        └──────────────┬────────────────┘
│  content script            │◄──── DOM read ────────┘
│    - JD detector           │
│    - JD extractor          │
│  background service worker │
│    - talks to backend      │
│  popup / side panel        │───► opens Review UI in new tab
└──────────┬─────────────────┘
           │  POST /jobs {jd_text, jd_meta}   (loopback HTTPS)
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Local Backend (FastAPI on 127.0.0.1:PORT, self-signed TLS)       │
│  ──────────────────────────────────────────────────────────────   │
│  routes/       jobs, bank, drafts, exports, providers            │
│  services/     ExperienceBank, Retriever, Tailor,                │
│                EvidenceLinker, KeywordAnalyzer, Renderer         │
│  db/           SQLite (Alembic migrations)                        │
│  providers/    OpenAIAdapter, AnthropicAdapter, OllamaAdapter    │
│  latex/        AST validator, template binder, pdflatex sandbox  │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ├──► User's LLM provider (per-call, over user's key)
           │
           └──► pdflatex subprocess (sandboxed, per-request tmpdir)

┌──────────────────────────────┐
│  Web Review UI (React SPA)   │  served from backend at /ui
│  ──────────────────────────  │
│  - Draft ↔ base diff         │
│  - Evidence matrix           │
│  - Keyword coverage          │
│  - Per-bullet approve/edit    │
│  - Export → PDF + .tex        │
└──────────────────────────────┘
```

**Trust boundary summary.** The extension trusts only the local backend. The backend trusts nothing on the network except the exact provider endpoint the user configured. See [`security-and-privacy.md`](security-and-privacy.md).

## 2. Components

### 2.1 Chrome extension (`apps/extension`)

- Manifest V3, TypeScript, Vite build.
- **Content script** injected into a curated allowlist of JD-hosting origins (see permissions rationale in [`security-and-privacy.md`](security-and-privacy.md#extension-permissions)). Runs per-site *extractors* (LinkedIn, Greenhouse, Lever, Ashby, Workday) plus a generic fallback that uses Readability-style heuristics.
- **JD detector** returns `{ present: bool, confidence: float, region: DOMRect, source: 'linkedin' | ... | 'generic' }`. Only sends data on user action.
- **Background service worker** owns the connection to the local backend (loopback, self-signed cert pinned on first run). No network egress to anywhere else.
- **UI surface** is a side panel with a single primary button; opens the review UI in a new tab once the draft is ready.

### 2.2 Local backend (`apps/backend`)

FastAPI + Uvicorn bound to `127.0.0.1`. SQLite database in the OS-appropriate app-data directory. Alembic for migrations. Pydantic v2 for all wire schemas (shared with the frontend via generated TypeScript types).

Key services:

| Service | Responsibility |
|---|---|
| `ExperienceBank` | CRUD over the bank; import from LaTeX/PDF; export to YAML |
| `Retriever` | Given a JD, ranks bank entries by relevance (BM25 baseline + optional embedding rerank if the provider supports embeddings) |
| `Tailor` | Prompts the provider to *select and rephrase* retrieved entries; returns candidate bullets with source `evidence_id`s |
| `EvidenceLinker` | For each candidate bullet, verifies token overlap with cited evidence; classifies as `verbatim` / `paraphrased` / `inferred` / `unsupported` |
| `KeywordAnalyzer` | Extracts JD requirements (skills, seniority signals, must-haves); computes coverage against the tailored draft |
| `Renderer` | Binds an approved draft into the `templates/resume.template.tex` family (optionally overlaid by a private file such as `.private/alan-resume-source.tex`); validates LaTeX AST; compiles PDF in a sandbox |

### 2.3 Web review UI (`apps/web`)

React 18 SPA served by the backend at `/ui`. State lives in the backend; the SPA is a view over `/api/drafts/{id}`. Three panes:

1. **Base vs. tailored diff** (Monaco diff view over the two `.tex` sources).
2. **Bullet inspector** — click any bullet in the tailored preview; sidebar shows evidence, classification badge, edit box.
3. **Coverage/gap panel** — keyword coverage matrix, unsupported-claim list, gap list.

Export flow: SPA calls `/api/drafts/{id}/export`; backend re-runs the evidence linker on the current state; refuses if any bullet is `unsupported` or `inferred`-and-unapproved. On success returns `{ pdf_path, tex_path }`.

## 3. Provider adapter interface

All LLM interaction is through this interface. Nothing else in the codebase may import a provider SDK directly. CI enforces this (a grep-based lint against `openai`, `anthropic`, `ollama` imports outside `packages/providers/*`).

```python
# packages/providers/base.py
from typing import Protocol, Iterable, TypedDict, Literal

class ProviderCapability(TypedDict):
    structured_output: bool     # native JSON/schema mode
    embeddings: bool            # exposes an embeddings endpoint
    tool_use: bool              # function-calling
    max_context_tokens: int
    streams: bool

class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str

class ProviderAdapter(Protocol):
    name: str                   # "openai" | "anthropic" | "ollama" | ...
    def capabilities(self) -> ProviderCapability: ...
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def health(self) -> tuple[bool, str]: ...
```

Adapters live in `packages/providers/{openai,anthropic,ollama}/`. Each adapter owns its own credential resolution:

- `OpenAIAdapter`: reads key from OS keychain under the app namespace.
- `AnthropicAdapter`: same.
- `OllamaAdapter`: no key; connects to `http://localhost:11434` by default.

A `NullAdapter` is used in tests and offline mode; it returns deterministic fixtures.

Feature gating: if a service wants structured output but the active adapter reports `structured_output: false`, it falls back to a JSON-mode prompt + Pydantic re-parse with retry.

## 4. Tailoring pipeline (single request)

```
JD text ─► KeywordAnalyzer ─► requirements[]
   │
   ▼
JD text + requirements ─► Retriever ─► ranked bank entries[]
   │
   ▼
requirements + entries ─► Tailor (LLM call) ─► candidate bullets[]
                                                    │
                                                    │  each bullet cites
                                                    │  evidence_id(s)
                                                    ▼
                                          EvidenceLinker
                                                    │
                                                    ▼
                                classified bullets: verbatim /
                                paraphrased / inferred / unsupported
                                                    │
                                                    ▼
                                          Draft (persisted)
                                                    │
                             ┌──────────────────────┼────────────────────┐
                             ▼                      ▼                    ▼
                    coverage report          gap list             review UI
```

The Tailor prompt is constructed to include:
- the JD text and extracted requirements,
- only the top-K retrieved bank entries with their `evidence_id`s,
- the LaTeX section skeleton to fill,
- a hard instruction: *every emitted bullet must include a `cites: [evidence_id, ...]` field; if no evidence supports a requirement, emit it to a `gaps` list instead of inventing a bullet.*

Structured output enforced via provider's JSON mode when available; otherwise via re-parse with retry (max 2). Malformed outputs after retries become an error surfaced in the UI — never a silent skip.

## 5. Evidence linker

Given a candidate bullet and its cited `evidence_id`s:

1. Tokenize both bullet and evidence texts (case-folded, stopword-preserved for verbs).
2. Compute the set of *content tokens* in the bullet not present in any cited evidence.
3. Extract numeric tokens (digits, percentages, "10+", "50 hiring managers") from the bullet.
4. Classify:
   - **`verbatim`** — bullet is a substring/near-substring of cited evidence (≥ 90% token overlap, no new numerics).
   - **`paraphrased`** — ≥ 70% token overlap, no new numerics, no new named entities.
   - **`inferred`** — < 70% token overlap OR new non-numeric content tokens present in evidence semantically (soft check via embedding similarity if the provider supports it, else marked `inferred` conservatively).
   - **`unsupported`** — new numeric tokens not in cited evidence, OR new named entities not in cited evidence, OR the bullet claims a scope (team size, timeline, impact) absent from evidence.

The linker's classifier is deterministic and testable. It is the single gate on export.

## 6. LaTeX validation strategy

Three layers, cheap → expensive:

### 6.1 Structural validation (AST-level, no shellout)

We parse the generated `.tex` with a small custom parser that understands the template's macros (`\resumeItem`, `\resumeSubheading`, `\resumeItemListStart/End`, etc.). We validate:

- Balanced `{}` and environments.
- All commands used exist in a per-template allowlist.
- No `\input`, `\include`, `\write18`, `\immediate\write`, `\catcode`, `\usepackage` outside the template preamble.
- No user-supplied text contains unescaped `#`, `%`, `&`, `_`, `$`, `^`, `~`, `\` outside math mode; the binder escapes these before insertion.
- Item counts per section within the template's supported range.

Rejects at this layer are user-visible with pinpointed offsets.

### 6.2 Injection/sandbox posture

`pdflatex` runs with:
- `-no-shell-escape` (unconditionally),
- CPU and wall-clock timeouts (default 30s),
- a per-request temporary directory as `--output-directory`,
- restricted `TEXMFHOME` pointing at a read-only bundled tree,
- no network via the OS sandbox (nsjail on Linux, sandbox-exec on macOS, Job Object + AppContainer on Windows where feasible; otherwise a plain subprocess with the other restrictions and a documented residual risk).

### 6.3 Behavioral validation (post-compile)

After `pdflatex`:
- PDF page count == 1 for one-page mode (else overflow indicator).
- Extracted text is non-empty and contains the user's name.
- ATS smoke check: extract text with `pdftotext`; assert no rendering-only glyphs replaced content characters; assert font is embedded and not a "type-3 raster" fallback.

## 7. Data flow, at a glance

| Step | Actor | Data | Destination |
|---|---|---|---|
| 1 | Extension content script | JD DOM region | Local backend `POST /jobs` |
| 2 | Backend | JD + top-K bank entries | User's chosen LLM provider |
| 3 | Provider | Candidate bullets JSON | Backend |
| 4 | Backend | Draft, coverage, gaps | SQLite + review UI |
| 5 | User in review UI | Approve/edit decisions | Backend |
| 6 | Backend | Final `.tex` | `pdflatex` sandbox |
| 7 | Backend | `.pdf` + `.tex` | User download |

At no point does user data traverse a server operated by this project.

## 8. Testing strategy

- **Unit:** every service, especially the evidence linker (property-based tests: no bullet with a new numeric token ever classifies below `inferred`).
- **Fixture regression:** `(JD, bank) → expected classified bullets, expected gaps, expected keyword coverage`. Snapshots checked into the repo; changes require review.
- **End-to-end:** headless Chrome + local backend + `NullAdapter` (deterministic model) → PDF exists, PDF text contains expected content.
- **Compile CI:** `templates/resume.template.tex` and the fixture-generated drafts must all compile. (The maintainer's `.private/alan-resume-source.tex` is git-ignored and therefore not exercised in CI; it is compiled locally.)

## 9. Deferred / out of scope for MVP

- Multi-template support (v1 ships one template).
- Cloud sync of the bank.
- Cover letter generation.
- Non-Chromium browsers.
- Hosted mode / SaaS.

See [`roadmap.md`](roadmap.md) for phasing.
