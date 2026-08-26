# Data Model

All schemas are authoritative here. Backend Pydantic and frontend Zod are generated/derived from these; discrepancies are bugs in codegen, not in this document.

Types below are shown in a TypeScript-ish notation for readability. IDs are ULIDs unless noted.

## 1. Overview

Three top-level entities plus supporting types:

- **`ExperienceBank`** — the user's canonical source of truth about themselves.
- **`Job`** — a captured JD from the extension.
- **`Draft`** — a tailored resume artifact tied to a `Job` and a `Bank` snapshot, containing evidence-linked bullets ready for review and export.

Everything in a Draft references entries from the Bank by ID, never by copy. This lets the review UI show live provenance and detect bank edits that would invalidate a draft.

## 2. Experience bank

```ts
type ExperienceBank = {
  bank_id: ULID;
  owner: { name: string; email: string; links: Link[]; phone?: string; citizenship?: string };
  education: EducationEntry[];
  experiences: ExperienceEntry[];
  projects: ProjectEntry[];
  leadership: LeadershipEntry[];
  skills: SkillGroup[];
  evidence: EvidenceItem[];       // free-form supporting artifacts
  created_at: ISOString;
  updated_at: ISOString;
  version: int;                    // monotonic; bumped on any mutation
};

type Link = { label: string; url: string; kind: "linkedin"|"github"|"web"|"other" };
```

### 2.1 Education / Experience / Project / Leadership entries

All four share a common shape (an entry has bullets; bullets carry evidence). The differences are metadata-only.

```ts
type EntryCommon = {
  entry_id: ULID;
  title: string;                  // "AI/ML Engineer Intern -- WatsonX Orchestrate"
  organization: string;           // "IBM, Silicon Valley Lab"
  location?: string;              // "San Jose, CA"
  start: YearMonth;               // "2026-05"
  end: YearMonth | "present";
  bullets: BulletEntry[];
  tags: string[];                 // free-form: "ai", "rag", "governance"
};

type ExperienceEntry = EntryCommon & { kind: "experience"; role: string };
type EducationEntry  = EntryCommon & { kind: "education"; degree: string; gpa?: string; coursework?: string[]; awards?: string[] };
type ProjectEntry    = EntryCommon & { kind: "project"; url?: string };
type LeadershipEntry = EntryCommon & { kind: "leadership"; role: string };
```

### 2.2 Bullets

A **bullet** is the smallest unit that can appear on a rendered resume. Every bullet in the bank carries the user's own words; the tailor may rephrase them, but the original stays as the evidence anchor.

```ts
type BulletEntry = {
  bullet_id: ULID;
  text: string;                   // the user's phrasing (source of truth)
  evidence_ids: ULID[];           // references to EvidenceItems
  quantities: Quantity[];         // extracted numbers with units and provenance
  named_entities: string[];       // orgs, products, technologies
  scope?: {                       // structured claims the user endorses
    team_size?: int;
    leadership?: "led"|"co-led"|"contributed"|null;
    impact_units?: string[];      // "users", "hiring managers", "documents"
  };
  do_not_paraphrase: boolean;     // if true, tailor may only include verbatim
};

type Quantity = {
  raw: string;                    // "50+ hiring managers"
  value_min: number;              // 50
  value_max?: number;
  unit: string;                   // "hiring managers"
  approximate: boolean;           // "+", "~", "over"
};
```

**Invariant.** Every `BulletEntry` must have `evidence_ids.length >= 1`. Bullets with no evidence cannot be created; the UI requires the user to link at least one evidence item at bullet-creation time.

### 2.3 Evidence

Evidence is the *why we can claim this* store. It can be free-form.

```ts
type EvidenceItem = {
  evidence_id: ULID;
  kind: "note" | "artifact" | "link" | "email" | "commit" | "pdf" | "screenshot";
  title: string;
  body: string;                   // user's raw text; may be long
  attachments?: FileRef[];        // local paths under app data dir
  external_url?: string;
  captured_at?: ISOString;        // when it happened
  added_at: ISOString;            // when the user added it
};
```

The evidence store is never sent to the LLM in full — only the specific evidence items linked to the bullets being retrieved for a given tailoring run.

### 2.4 Skills

```ts
type SkillGroup = {
  group: "Languages" | "ML & AI" | "Infrastructure" | "Quantum & FL" | string;
  skills: Skill[];
};

type Skill = {
  name: string;                   // "Python"
  evidence_ids: ULID[];           // must have >=1 — same invariant as bullets
  proficiency?: "familiar" | "working" | "proficient" | "expert";
};
```

Same invariant as bullets: a skill without evidence cannot be included in a tailored resume. The UI can show "unevidenced" skills to prompt the user to add evidence.

## 3. Job

```ts
type Job = {
  job_id: ULID;
  captured_at: ISOString;
  source: {
    provider: "linkedin"|"greenhouse"|"lever"|"ashby"|"workday"|"generic";
    url: string;                  // full URL, kept locally
    org?: string;
    role_title?: string;
  };
  raw_text: string;               // extracted JD text (post-clean)
  raw_html_snippet?: string;      // small provenance snippet
  requirements: Requirement[];    // filled by KeywordAnalyzer
};

type Requirement = {
  requirement_id: ULID;
  text: string;                   // "Experience with LLM agents"
  category: "must_have" | "nice_to_have" | "responsibility" | "skill";
  keywords: string[];             // ["LLM", "agents"]
  seniority_signal?: "intern"|"junior"|"mid"|"senior"|"staff"|null;
};
```

## 4. Draft (tailored resume artifact)

```ts
type Draft = {
  draft_id: ULID;
  job_id: ULID;
  bank_id: ULID;
  bank_version: int;              // snapshot; UI warns if bank has moved on
  template_id: string;            // e.g., "alan-abhijha-single-page-v1"
  created_at: ISOString;
  status: "generating" | "ready_for_review" | "approved" | "exported" | "invalidated";

  sections: DraftSection[];
  gaps: Gap[];                    // JD requirements with no supporting evidence
  keyword_coverage: KeywordCoverage;

  export?: {
    exported_at: ISOString;
    tex_path: string;
    pdf_path: string;
    pdf_page_count: int;
    sha256_tex: string;
    sha256_pdf: string;
  };
};

type DraftSection = {
  section_id: ULID;
  kind: "education"|"experience"|"projects"|"leadership"|"skills";
  entries: DraftEntry[];
};

type DraftEntry = {
  source_entry_id: ULID;          // ExperienceBank entry
  bullets: DraftBullet[];
};

type DraftBullet = {
  draft_bullet_id: ULID;
  source_bullet_id: ULID;         // ExperienceBank bullet
  cited_evidence_ids: ULID[];     // subset of source bullet's evidence
  original_text: string;          // the source bullet's text, snapshotted
  rewritten_text: string;         // what the tailor produced (or user edit)
  classification: BulletClassification;
  edited_by_user: boolean;
  approved: boolean;              // required true to export if inferred
  approved_at?: ISOString;
};

type BulletClassification = {
  label: "verbatim" | "paraphrased" | "inferred" | "unsupported";
  token_overlap: float;           // 0..1
  new_numeric_tokens: string[];   // must be empty for non-unsupported
  new_named_entities: string[];   // must be empty for non-unsupported
  reason: string;                 // human-readable
};

type Gap = {
  requirement_id: ULID;
  requirement_text: string;
  reason: "no_matching_evidence" | "insufficient_specificity" | "user_deferred";
};

type KeywordCoverage = {
  jd_keywords: string[];
  matched: { keyword: string; bullet_ids: ULID[] }[];
  unmatched: string[];
  coverage_ratio: float;          // matched / total
};
```

**Export gate (enforced at `/api/drafts/{id}/export`):**
- All `DraftBullet.classification.label != "unsupported"`.
- All bullets with `label == "inferred"` have `approved == true`.
- LaTeX AST validation passes.
- `pdflatex` sandbox produces a page count consistent with template mode.

## 5. Provider configuration

Kept out of the SQLite DB in v1. See [`security-and-privacy.md`](security-and-privacy.md#credentials).

```ts
type ProviderConfig = {
  provider: "openai" | "anthropic" | "ollama";
  model: string;                  // "gpt-4o-mini" | "claude-sonnet-4-6" | "llama3.1:70b"
  base_url?: string;              // for self-hosted / gateway
  // secret_ref is a keychain lookup key, NOT the secret itself
  secret_ref: string;             // e.g., "job-resume-agent:openai:default"
};
```

## 6. Migrations & versioning

- SQLite with Alembic migrations. `bank.version` bumps on any mutation of bank entries or evidence; drafts carry the version they were generated against and warn if outdated.
- Schema breaking changes ship with a migration and a fixture update; see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## 7. Import / export

- **Import LaTeX:** parser reads the reference template family; maps `\resumeSubheading` blocks to entries and `\resumeItem` to bullets. Every imported bullet is created with a single auto-generated `EvidenceItem` of kind `"note"` whose `body` is the bullet text — the user is prompted to enrich these before generation.
- **Import PDF:** best-effort text extraction with `pdftotext` + section-heading heuristics; results always go into a *review-before-save* modal.
- **Export bank:** YAML dump of the full bank + evidence to a user-chosen path. Symmetric with the example at [`example-experience-bank.yaml`](example-experience-bank.yaml).

## 8. Deletion

`wipe` removes:
1. SQLite DB file.
2. All files under the app-data directory (including cached PDFs, imported attachments).
3. OS keychain entries under the `job-resume-agent:*` namespace.
4. The extension's `chrome.storage.local` (documented user step; the extension cannot delete keychain data programmatically).

Deletion is idempotent and dry-run-able.
