from resume_agent.keywords import (
    content_token_set,
    extract_keywords,
    tokenize,
)


def test_extract_keywords_captures_acronyms_and_frameworks():
    text = (
        "Looking for an engineer with Python, PyTorch, and FastAPI experience. "
        "Bonus: MCP, RAG, and LLM tooling. Also Microsoft Graph."
    )
    kws = extract_keywords(text)
    kws_lower = {k.lower() for k in kws}
    assert "python" in kws_lower
    assert "pytorch" in kws_lower
    assert "fastapi" in kws_lower
    assert "mcp" in kws_lower
    assert "rag" in kws_lower
    assert "microsoft graph" in kws_lower


def test_extract_keywords_is_deterministic():
    text = "Python, Docker, and MCP. Also MCP, Docker, Python."
    a = extract_keywords(text)
    b = extract_keywords(text)
    assert a == b
    # first occurrence wins
    assert a.index("Python") < a.index("Docker") or a[0] in {"Python", "Docker", "MCP"}


def test_stopwords_removed():
    tokens = tokenize("The quick brown fox jumps over the lazy dog")
    assert "the" not in tokens
    assert "quick" in tokens


def test_content_token_set_lowercases():
    s = content_token_set("PyTorch and MCP")
    assert "pytorch" in s
    assert "mcp" in s


def test_extract_keywords_ignores_corporate_boilerplate_phrases():
    """Regression test: a real scraped job posting bundles Title-Case
    company chrome (investor names, "Who We Are" headers, legal/compensation
    text) in with the actual requirements. None of that should surface as a
    fake 'requirement' -- it silently starved tailor_resume of real matches
    and produced experience-only resumes. See the keywords.py module
    docstring for the allowlist-by-technical-noun approach that fixes this."""
    text = (
        "Who We Are\n\n"
        "Acme is backed by Sequoia Capital, General Catalyst, and Felicis "
        "Ventures, with a $5B valuation from CapitalG.\n\n"
        "What You Bring\n\n"
        "Strong background in Distributed Systems and Backend Engineering. "
        "Experience with Python, Kubernetes, and Postgres required.\n\n"
        "Pay Disclosure\n\n"
        "Restricted Stock Units and an Estimated Hourly Pay range apply. "
        "See our Candidate Privacy Policy for details.\n\n"
        "Equal Opportunity Employer. Acme is proud to be an Equal "
        "Opportunity Employer."
    )
    kws = extract_keywords(text)
    kws_lower = {k.lower() for k in kws}

    # Real requirements must survive.
    assert "python" in kws_lower
    assert "kubernetes" in kws_lower
    assert "postgres" in kws_lower
    assert "distributed systems" in kws_lower
    assert "backend engineering" in kws_lower

    # Corporate/legal/investor chrome must not be captured as a keyword.
    for junk in (
        "sequoia capital",
        "general catalyst",
        "felicis ventures",
        "capitalg",
        "who we are",
        "what you bring",
        "pay disclosure",
        "restricted stock units",
        "estimated hourly pay",
        "candidate privacy policy",
        "equal opportunity employer",
        "equal opportunity",
    ):
        assert junk not in kws_lower, f"boilerplate leaked into keywords: {junk!r}"


def test_extract_keywords_ignores_html_data_attribute_noise():
    """Regression test: HTML that wasn't fully stripped to plain text (e.g.
    a scraper that left data-* attributes or CSS class fragments inline)
    must not spray junk tokens like 'content-intro' or 'data-list-tree'
    into the requirement list."""
    text = (
        "content-intro data-stringify-type unordered-list data-list-tree "
        "font-size content-pay-transparency pay-input pay-range USD "
        "Experience with React and TypeScript required."
    )
    kws = extract_keywords(text)
    kws_lower = {k.lower() for k in kws}
    assert "react" in kws_lower
    assert "typescript" in kws_lower
    for junk in ("content-intro", "data-stringify-type", "data-list-tree", "content-pay-transparency"):
        assert junk not in kws_lower
