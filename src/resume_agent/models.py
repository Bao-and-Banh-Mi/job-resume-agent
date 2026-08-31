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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


Verdict = Literal["covered", "partial", "gap"]


class AssessedRequirement(_Base):
    """One requirement, as read out of the posting *by the calling agent*.

    The agent supplies ``text`` (a requirement it identified in the JD) plus
    the bank ids it believes support that requirement. The server does not
    trust the verdict: it re-checks that every cited id exists, and downgrades
    any ``covered``/``partial`` claim that cites nothing. That check is what
    keeps a confident model from inflating its own coverage number.
    """

    text: str
    category: RequirementCategory = "skill"
    verdict: Verdict = "gap"
    # Accepts bullet ids AND entry ids. Degree/GPA/coursework requirements
    # are properties of an education *entry*, which has no bullets, so
    # restricting this to bullet ids forced agents to either cite unrelated
    # experience or report a false gap. Both live runs hit this.
    supporting_bullet_ids: list[str] = Field(
        default_factory=list, alias="supporting_ids"
    )
    supporting_skills: list[str] = Field(default_factory=list)
    note: str = ""


class FitReport(_Base):
    """Validated output of ``analyze_fit``."""

    job_id: str
    total_requirements: int
    covered: list[AssessedRequirement] = Field(default_factory=list)
    partial: list[AssessedRequirement] = Field(default_factory=list)
    gaps: list[AssessedRequirement] = Field(default_factory=list)
    coverage_ratio: float = 0.0
    weighted_coverage: float = 0.0
    must_have_gaps: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    recommendation: str = ""


class SelectedBullet(_Base):
    """A bullet the agent chose to include.

    ``rewritten_text`` is optional. When present it is *checked against the
    original bullet and its evidence* by the linker before it can be
    exported, so rephrasing for a posting's vocabulary is allowed but
    inventing facts is not.
    """

    bullet_id: str
    rewritten_text: Optional[str] = None


class SelectedEntry(_Base):
    entry_id: str
    bullets: list[SelectedBullet] = Field(default_factory=list)


class SelectedSection(_Base):
    # Accepts BOTH the singular entry-kind spelling that ``load_bank``'s
    # catalog reports ("project") and the plural section spelling used
    # internally ("projects"). A live agent run tripped on exactly this:
    # the catalog labels entries "project", so the model naturally wrote
    # "project" here and got a validation error. Making the tool contradict
    # its own output is our bug, not the caller's, so we normalise instead
    # of rejecting.
    kind: Literal[
        "education", "experience", "projects", "leadership", "project"
    ]
    entries: list[SelectedEntry] = Field(default_factory=list)

    @field_validator("kind", mode="after")
    @classmethod
    def _normalise_kind(cls, v: str) -> str:
        return "projects" if v == "project" else v


class SelectedSkillGroup(_Base):
    group: str
    skills: list[str] = Field(default_factory=list)


class ResumeSelection(_Base):
    """The agent's editorial decision, handed to ``tailor_resume``.

    Everything here is a *reference* into the loaded bank. There is no field
    through which free-form resume content can enter, except
    ``SelectedBullet.rewritten_text``, which is gated by the evidence linker.
    """

    sections: list[SelectedSection] = Field(default_factory=list)
    skills: list[SelectedSkillGroup] = Field(default_factory=list)
    # Set true only when a human has reviewed rephrasings the linker judged
    # 'inferred'. Unsupported bullets can never be approved this way.
    accept_inferred: bool = False
    rationale: str = ""


class RequirementMatch(_Base):
    """Which bank evidence supports a single JD requirement."""

    requirement_id: str
    requirement_text: str
    matched_keywords: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    bullet_ids: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)


class SkillsMatch(_Base):
    """Report emitted by the ``match_skills`` MCP tool.

    Pure summary: no draft is created, no bullets are rewritten. An agent
    is expected to call this first, then decide whether to invoke
    ``tailor_resume`` for the same ``job_id``.
    """

    job_id: str
    total_requirements: int
    matched: list[RequirementMatch] = Field(default_factory=list)
    unmatched: list[RequirementMatch] = Field(default_factory=list)
    coverage_ratio: float = 0.0
