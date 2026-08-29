"""Renders a ``Draft`` to LaTeX using the public template's macros.

The renderer never invokes ``pdflatex``. It produces a ``.tex`` string that
matches the shape of ``templates/resume.template.tex`` and reuses the exact
``\\resumeItem``/``\\resumeSubheading``/``\\resumeItemListStart`` macros so the
result can be compiled with the same toolchain.

All user-supplied strings are escaped through :func:`escape_latex` before
insertion. That escaper is the single place LaTeX-sensitive characters are
handled; it is exercised by the LaTeX-escaping tests.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Draft, DraftEntry, DraftSection, SkillGroup

# Ordering matters: backslash must be replaced first, otherwise later
# replacements will double-escape their own backslashes.
_ESCAPE_TABLE: list[tuple[str, str]] = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]


def escape_latex(text: str) -> str:
    """Escape all LaTeX-special characters in ``text``."""
    if text is None:
        return ""
    # Protect generated LaTeX commands while escaping user braces and other
    # special characters. This prevents ``\\textbackslash{}`` from becoming
    # ``\\textbackslash\\{\\}``.
    sentinel = "RESUMEAGENTBACKSLASHSENTINEL"
    out = text.replace("\\", sentinel)
    for src, dst in _ESCAPE_TABLE[1:]:
        out = out.replace(src, dst)
    return out.replace(sentinel, r"\textbackslash{}")


def _fmt_date_range(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{start} -- {end}"
    if end:
        return end
    if start:
        return start
    return ""


def _render_experience_entry(entry: DraftEntry) -> str:
    header = (
        "    \\resumeSubheading\n"
        f"      {{{escape_latex(entry.organization)}}}{{{escape_latex(entry.location or '')}}}\n"
        f"      {{{escape_latex(entry.role or entry.title)}}}{{{escape_latex(_fmt_date_range(entry.start, entry.end))}}}\n"
    )
    if not entry.bullets:
        return header
    lines = ["      \\resumeItemListStart"]
    for b in entry.bullets:
        lines.append(f"        \\resumeItem{{{escape_latex(b.rewritten_text)}}}")
    lines.append("      \\resumeItemListEnd")
    return header + "\n".join(lines) + "\n"


def _render_project_entry(entry: DraftEntry) -> str:
    header = (
        "    \\resumeSubheading\n"
        f"      {{{escape_latex(entry.title)}}}{{{escape_latex(entry.organization)}}}\n"
        f"      {{{escape_latex(entry.role or 'Project')}}}{{{escape_latex(_fmt_date_range(entry.start, entry.end))}}}\n"
    )
    if not entry.bullets:
        return header
    lines = ["      \\resumeItemListStart"]
    for b in entry.bullets:
        lines.append(f"        \\resumeItem{{{escape_latex(b.rewritten_text)}}}")
    lines.append("      \\resumeItemListEnd")
    return header + "\n".join(lines) + "\n"


def _render_education_entry(entry: DraftEntry) -> str:
    header_line = entry.degree or entry.title
    gpa = f"; GPA: {entry.gpa}" if entry.gpa else ""
    header = (
        "    \\resumeSubheading\n"
        f"      {{{escape_latex(entry.organization)}}}{{{escape_latex(entry.location or '')}}}\n"
        f"      {{{escape_latex(header_line + gpa)}}}{{{escape_latex(entry.end or '')}}}\n"
    )
    inner: list[str] = []
    if entry.coursework:
        inner.append(
            "        \\resumeItem{\\textbf{Coursework:} "
            f"{escape_latex(', '.join(entry.coursework))}}}"
        )
    for b in entry.bullets:
        inner.append(f"        \\resumeItem{{{escape_latex(b.rewritten_text)}}}")
    if not inner:
        return header
    return header + "      \\resumeItemListStart\n" + "\n".join(inner) + "\n      \\resumeItemListEnd\n"


def _render_section(section: DraftSection) -> str:
    title_map = {
        "experience": "Experience",
        "projects": "Projects \\& Research",
        "leadership": "Leadership",
        "education": "Education",
        "skills": "Skills",
    }
    title = title_map.get(section.kind, section.kind.title())

    if section.kind == "skills":
        # Skip the header entirely when no skills matched the JD.
        if not section.skill_groups:
            return ""
        return _render_skills_section(title, section.skill_groups)

    # Non-skills sections: skip if the tailor emitted no entries.
    if not section.entries:
        return ""

    body_lines = [f"\\section{{{title}}}", "  \\resumeSubHeadingListStart"]
    for entry in section.entries:
        if section.kind == "experience":
            body_lines.append(_render_experience_entry(entry))
        elif section.kind == "projects":
            body_lines.append(_render_project_entry(entry))
        elif section.kind == "leadership":
            body_lines.append(_render_experience_entry(entry))
        elif section.kind == "education":
            body_lines.append(_render_education_entry(entry))
    body_lines.append("  \\resumeSubHeadingListEnd")
    return "\n".join(body_lines) + "\n"


def _render_skills_section(title: str, groups: list[SkillGroup]) -> str:
    lines = [
        f"\\section{{{title}}}",
        " \\begin{itemize}[leftmargin=0.15in, label={}, topsep=2pt, parsep=0pt]",
        "    \\small{\\item{",
    ]
    for g in groups:
        skills_text = ", ".join(escape_latex(s.name) for s in g.skills)
        lines.append(f"     \\textbf{{{escape_latex(g.group)}:}} {skills_text} \\\\")
    lines.extend(["    }}", " \\end{itemize}"])
    return "\n".join(lines) + "\n"


def _render_header(draft: Draft) -> str:
    owner = draft.owner
    linkedin = next((l for l in owner.links if l.kind == "linkedin"), None)
    github = next((l for l in owner.links if l.kind == "github"), None)
    parts = [
        "\\begin{center}",
        f"    \\textbf{{\\Huge \\scshape {escape_latex(owner.name)}}} \\\\ \\vspace{{2pt}}",
        f"    \\href{{mailto:{escape_latex(owner.email)}}}{{\\textcolor{{BlueViolet}}"
        f"{{\\enspace \\textbf{{{escape_latex(owner.email)}}}}}}}",
    ]
    if linkedin:
        parts[-1] += " $|$"
        parts.append(
            f"    \\href{{{escape_latex(linkedin.url)}}}{{\\textcolor{{BlueViolet}}"
            f"{{\\faLinkedin\\enspace \\textbf{{{escape_latex(linkedin.label)}}}}}}}"
        )
    if github:
        parts[-1] += " $|$"
        parts.append(
            f"    \\href{{{escape_latex(github.url)}}}{{\\textcolor{{BlueViolet}}"
            f"{{\\faGithub\\enspace \\textbf{{{escape_latex(github.label)}}}}}}}"
        )
    if owner.phone:
        parts[-1] += " $|$"
        parts.append(f"    \\small {{\\textbf{{{escape_latex(owner.phone)}}}}}")
    if owner.citizenship:
        parts[-1] += " $|$"
        parts.append(f"    {{\\textbf{{{escape_latex(owner.citizenship)}}}}}")
    parts.append("\\end{center}")
    return "\n".join(parts) + "\n"


def _load_template_preamble(template_path: Path) -> str:
    """Extract everything up to (but not including) ``\\begin{document}``."""
    text = template_path.read_text(encoding="utf-8")
    # Match the actual document boundary, not a comment that happens to
    # mention ``\\begin{document}`` in the template instructions.
    match = re.search(r"(?m)^\\begin\{document\}\s*$", text)
    if match is None:
        raise ValueError(f"template {template_path} is missing \\begin{{document}}")
    return text[: match.start()]


def render_draft(draft: Draft, template_path: str | Path) -> str:
    """Render a full ``.tex`` source string for the given draft."""
    preamble = _load_template_preamble(Path(template_path))
    body_sections = "\n".join(_render_section(s) for s in draft.sections)
    return (
        preamble
        + "\\begin{document}\n\n"
        + _render_header(draft)
        + "\n"
        + body_sections
        + "\n\\end{document}\n"
    )
