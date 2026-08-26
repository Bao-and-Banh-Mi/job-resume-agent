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
   (``Microsoft Graph``, ``Machine Learning``).

This is a heuristic, not an ontology. It is deterministic, testable, and
keeps zero surprises in the tailoring output.
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

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-]*")


def _looks_technical(token: str) -> bool:
    if len(token) < 2:
        return False
    lower = token.lower()
    if lower in _STOPWORDS:
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
    if "-" in token and lower not in _STOPWORDS:
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
        if phrase.lower() in _STOPWORDS or not phrase:
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
