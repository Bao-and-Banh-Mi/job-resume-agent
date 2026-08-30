"""Deterministic keyword analyzer.

Given a JD text, extract a stable list of skill/tool keywords. The POC does
not use an LLM. The approach:

1. Tokenize the JD (case-preserving so acronyms like ``RAG`` survive).
2. Keep tokens that look like technical terms:
   - all-uppercase acronyms (``LLM``, ``RAG``, ``API``, ``SQL``),
   - mixed-case identifiers (``PyTorch``, ``FastAPI``),
   - lowercase tokens matching a curated vocabulary,
   - hyphenated tech phrases (``multi-agent``),
3. Additionally capture 2-3 word phrases that are all-Titlecase or all-uppercase
   (``Microsoft Graph``, ``Machine Learning``) -- but ONLY when the phrase
   contains at least one word from a curated technical-noun allowlist
   (``_TECH_PHRASE_HEADS``). Real scraped job postings (Greenhouse, Workday,
   etc.) are full of Title-Case company chrome -- investor names, "Who We
   Are" headers, legal/compensation boilerplate -- that would otherwise be
   captured as fake "requirements." A blacklist of known-junk phrases is
   whack-a-mole (every company's boilerplate is different); allowlisting by
   technical-noun content bounds the false-positive surface instead.

This is a heuristic, not an ontology. It is deterministic and testable, but
it is a POC-quality approximation of "extract the required skills from a
JD" -- not a real NLP requirement extractor. See docs/roadmap.md for
planned improvements (e.g. a real KeywordAnalyzer backed by structured JD
parsing).
"""

from __future__ import annotations

import re
from collections import OrderedDict

# Vocab of lowercase technical tokens we want to keep. Extend as needed.
_LOWERCASE_TECH_VOCAB = frozenset(
    {
        "python", "java", "javascript", "typescript", "golang", "rust", "kotlin",
        "swift", "scala", "ruby", "php", "sql", "bash", "shell", "cuda",
        "pytorch", "tensorflow", "numpy", "pandas", "sklearn", "scikit-learn",
        "huggingface", "transformers", "langchain", "llamaindex", "mcp", "rag",
        "docker", "kubernetes", "linux", "unix", "git", "github", "gitlab",
        "fastapi", "flask", "django", "react", "vue", "svelte", "next", "nextjs",
        "node", "nodejs", "aws", "gcp", "azure", "terraform", "ansible",
        "mysql", "postgres", "postgresql", "mongodb", "redis", "kafka",
        "spark", "hadoop", "airflow", "dbt", "snowflake", "bigquery",
        "microservices", "grpc", "graphql", "rest", "api", "apis",
        "swiftui", "ios", "android", "flutter",
        "ml", "ai", "nlp", "cv", "llm", "llms", "agents", "agent",
        "quantum", "pennylane", "qiskit", "flower",
        "reinforcement", "learning", "federated", "embeddings", "retrieval",
        "multi-agent", "governance", "evaluation", "evaluations",
        "typescript", "chrome", "extension", "browser",
    }
)

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "at", "by", "from", "as", "is", "are", "be", "was", "were", "been",
        "will", "would", "should", "could", "may", "might", "can", "must",
        "we", "you", "our", "your", "their", "this", "that", "these", "those",
        "have", "has", "had", "do", "does", "did", "not", "no", "yes",
        "who", "what", "when", "where", "why", "how", "which", "than", "then",
        "if", "so", "but", "because", "while", "about", "into", "over", "under",
        "such", "some", "any", "all", "each", "every", "other", "same",
        "responsibilities", "requirements", "qualifications", "experience",
        "years", "year", "month", "months", "day", "days",
    }
)

# Multi-word Title-Case phrase extraction over arbitrary web/JD text is an
# unbounded surface: a blacklist of "known junk phrases" is whack-a-mole
# because every company's boilerplate (investor names, legal chrome,
# "Who We Are" style headers) is different. Instead we ALLOWLIST: a 2-3
# word Title-Case phrase is only kept as a candidate keyword if it contains
# at least one word from this curated set of technical compound-noun heads.
# This bounds the false-positive rate to "a real word from this list
# appeared in a non-technical phrase" rather than "any capitalized phrase
# anywhere in the page."
_TECH_PHRASE_HEADS = frozenset(
    {
        "engineering", "engineer", "science", "sciences", "systems", "system",
        "learning", "architecture", "structures", "algorithms", "algorithm",
        "networks", "network", "design", "development", "developer",
        "testing", "integration", "computing", "intelligence", "automation",
        "infrastructure", "security", "databases", "database", "frameworks",
        "framework", "software", "hardware", "backend", "frontend",
        "distributed", "cloud", "api", "apis", "sdk", "ui", "ux", "mobile",
        "web", "data", "analytics", "pipeline", "pipelines", "services",
        "service", "platform", "platforms", "scripting", "processing",
        "modeling", "simulation", "robotics", "embedded", "firmware",
        "protocol", "protocols", "encryption", "cryptography", "compiler",
        "compilers", "runtime", "virtualization", "containers", "container",
        "microservices", "orchestration", "deployment", "monitoring",
        "observability", "reliability", "scalability", "performance",
        "quantum", "blockchain", "cybersecurity", "graph", "graphs",
    }
)


def _phrase_looks_technical(phrase: str) -> bool:
    words = re.findall(r"[A-Za-z]+", phrase.lower())
    return any(w in _TECH_PHRASE_HEADS for w in words)


# Prefixes of hyphenated tokens that are HTML/CSS/data-attribute leftovers
# rather than real hyphenated compound words (e.g. "multi-agent"). These
# leak in when a JD source wasn't fully stripped to plain text.
_NON_TECH_HYPHEN_PREFIXES = (
    "data-", "content-", "pay-", "font-", "aria-", "class-", "style-",
)

# Single tokens that are common false positives for the acronym/mixed-case
# rules below: US state codes, generic HR/compensation acronyms, and a
# handful of specific non-technical tokens observed in real scraped JDs
# (company-style CamelCase names like "CapitalG" are not detectable by
# shape alone, so they are named explicitly rather than pattern-matched).
_TOKEN_DENYLIST = frozenset(
    {
        "rsus", "rsu", "ppe", "hq", "usd", "pto", "cpt", "hsa", "fsa",
        "eap", "ad", "dc", "top", "ff", "il", "wi", "ca", "ny", "tx",
        "capitalg",
    }
)


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-]*")


def _looks_technical(token: str) -> bool:
    if len(token) < 2:
        return False
    lower = token.lower()
    if lower in _STOPWORDS:
        return False
    if lower in _TOKEN_DENYLIST:
        return False
    if lower in _LOWERCASE_TECH_VOCAB:
        return True
    # Acronyms: all uppercase, at least 2 chars.
    if token.isupper() and any(c.isalpha() for c in token):
        return True
    # Mixed case identifiers: contains a lowercase and an uppercase after position 0.
    if any(c.isupper() for c in token[1:]) and any(c.islower() for c in token):
        return True
    # Hyphenated tech phrases like "multi-agent".
    if "-" in token and not lower.startswith(_NON_TECH_HYPHEN_PREFIXES):
        return True
    return False


def _extract_phrases(text: str) -> list[str]:
    """Capture short Title Case or ALL CAPS phrases like ``Microsoft Graph``."""
    phrases: list[str] = []
    pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})){1,2}\b"
    )
    for m in pattern.finditer(text):
        phrase = m.group(0)
        # Sentence-leading connectors can be absorbed by the Title Case
        # matcher (for example, "Also Microsoft Graph"). They are not part
        # of the technical phrase.
        phrase = re.sub(r"^(?:Also|And|The|A|An)\s+", "", phrase)
        if not phrase:
            continue
        if phrase.lower() in _STOPWORDS:
            continue
        if not _phrase_looks_technical(phrase):
            continue
        phrases.append(phrase)
    return phrases


def extract_keywords(text: str) -> list[str]:
    """Return a deterministic, de-duplicated list of technical keywords."""
    out: "OrderedDict[str, None]" = OrderedDict()
    for phrase in _extract_phrases(text):
        out.setdefault(phrase, None)
    for token in _TOKEN_RE.findall(text):
        if _looks_technical(token):
            out.setdefault(token, None)
    return list(out.keys())


def tokenize(text: str) -> list[str]:
    """Case-folded content tokens, minus stopwords. Used by the linker."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


def content_token_set(text: str) -> set[str]:
    return set(tokenize(text))
