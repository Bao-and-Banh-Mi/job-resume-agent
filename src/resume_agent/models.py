"""Pydantic v2 schemas for the POC.

Mirrors the shapes documented in `docs/data-model.md`. The POC intentionally
skips a few v1 concerns (ULID generation strategy, migrations, snapshotting
`bank_version`) that the docs call out as owned by the persistence layer;
those live outside the tailoring pipeline this package implements.

The models here are the API boundary that a future Chrome extension --- or
any other client --- would talk to via the MCP tools. Keeping them Pydantic
means the same shapes can be re-exposed as JSON Schema without a rewrite.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

BulletLabel = Literal["verbatim", "paraphrased", "inferred", "unsupported"]
EntryKind = Literal["education", "experience", "project", "leadership"]
RequirementCategory = Literal["must_have", "nice_to_have", "responsibility", "skill"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Link(_Base):
    label: str
    url: str
    kind: Literal["linkedin", "github", "web", "other"] = "other"


class Owner(_Base):
    name: str
    email: str
    phone: Optional[str] = None
    citizenship: Optional[str] = None
    links: list[Link] = Field(default_factory=list)


class Quantity(_Base):
    raw: str
    value_min: float
    value_max: Optional[float] = None
    unit: str = ""
    approximate: bool = False


class BulletEntry(_Base):
    bullet_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    named_entities: list[str] = Field(default_factory=list)
    do_not_paraphrase: bool = False


class EntryCommon(_Base):
    entry_id: str
    kind: EntryKind
    title: str
    organization: str
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    role: Optional[str] = None
    degree: Optional[str] = None
    gpa: Optional[str] = None
    coursework: list[str] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    bullets: list[BulletEntry] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Skill(_Base):
    name: str
    evidence_ids: list[str] = Field(default_factory=list)
    proficiency: Optional[Literal["familiar", "working", "proficient", "expert"]] = None


class SkillGroup(_Base):
    group: str
    skills: list[Skill] = Field(default_factory=list)


class EvidenceItem(_Base):
    evidence_id: str
    kind: Literal["note", "artifact", "link", "email", "commit", "pdf", "screenshot"] = "note"
    title: str = ""
    body: str = ""


class ExperienceBank(_Base):
    schema_version: int = 1
    owner: Owner
    education: list[EntryCommon] = Field(default_factory=list)
    experiences: list[EntryCommon] = Field(default_factory=list)
    projects: list[EntryCommon] = Field(default_factory=list)
    leadership: list[EntryCommon] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    def evidence_index(self) -> dict[str, EvidenceItem]:
        return {e.evidence_id: e for e in self.evidence}

    def all_entries(self) -> list[EntryCommon]:
        return [
            *self.education,
            *self.experiences,
            *self.projects,
            *self.leadership,
        ]


class Requirement(_Base):
    requirement_id: str
    text: str
    category: RequirementCategory = "skill"
    keywords: list[str] = Field(default_factory=list)


class JobDescription(_Base):
    """Input model for `set_job_description`.

    Kept API-neutral: a browser extension, a shell script, or a test all
    populate the same fields. `source_url` is optional so the model works
    for pasted-text sessions.
    """

    job_id: str
    captured_at: str
    source_url: Optional[str] = None
    source_provider: Literal[
        "linkedin", "greenhouse", "lever", "ashby", "workday", "generic"
    ] = "generic"
    org: Optional[str] = None
    role_title: Optional[str] = None
    raw_text: str
    requirements: list[Requirement] = Field(default_factory=list)


class BulletClassification(_Base):
    label: BulletLabel
    token_overlap: float
    new_numeric_tokens: list[str] = Field(default_factory=list)
    new_named_entities: list[str] = Field(default_factory=list)
    reason: str = ""


class DraftBullet(_Base):
    draft_bullet_id: str
    source_bullet_id: str
    source_entry_id: str
    cited_evidence_ids: list[str]
    original_text: str
    rewritten_text: str
    classification: BulletClassification
    edited_by_user: bool = False
    approved: bool = False


class DraftEntry(_Base):
    source_entry_id: str
    kind: EntryKind
    title: str
    organization: str
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    role: Optional[str] = None
    degree: Optional[str] = None
    gpa: Optional[str] = None
    coursework: list[str] = Field(default_factory=list)
    bullets: list[DraftBullet] = Field(default_factory=list)


class DraftSection(_Base):
    section_id: str
    kind: Literal["education", "experience", "projects", "leadership", "skills"]
    entries: list[DraftEntry] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)


class Gap(_Base):
    requirement_id: str
    requirement_text: str
    reason: Literal[
        "no_matching_evidence", "insufficient_specificity", "user_deferred"
    ] = "no_matching_evidence"


class KeywordCoverage(_Base):
    jd_keywords: list[str]
    matched: list[dict] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    coverage_ratio: float = 0.0


class Draft(_Base):
    draft_id: str
    job_id: str
    template_id: str = "public-single-page-v1"
    created_at: str
    status: Literal[
        "generating", "ready_for_review", "approved", "exported", "invalidated"
    ] = "ready_for_review"
    owner: Owner
    sections: list[DraftSection] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    keyword_coverage: KeywordCoverage
