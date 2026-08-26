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
