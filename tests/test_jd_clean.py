"""The JD cleaner is the front door: everything downstream reads its output."""

from __future__ import annotations

from resume_agent.jd_clean import clean_jd_text, looks_like_html


def test_strips_script_and_style_bodies():
    raw = """
    <html><head><style>.a{color:red}</style></head>
    <body><script>var x = {"salary": 100};</script>
    <p>We need Python and Go.</p></body></html>
    """
    out = clean_jd_text(raw)
    assert "color:red" not in out
    assert "var x" not in out
    assert "salary" not in out
    assert "We need Python and Go." in out


def test_block_tags_become_line_breaks_not_joined_words():
    raw = "<li>Python</li><li>Golang</li>"
    out = clean_jd_text(raw)
    # Without newline insertion these would merge into "PythonGolang".
    assert "PythonGolang" not in out
    assert "Python" in out and "Golang" in out


def test_unescapes_entities_and_nbsp():
    out = clean_jd_text("<p>R&amp;D&nbsp;team</p>")
    assert "R&D" in out
    assert "\xa0" not in out


def test_idempotent_on_clean_text():
    text = "We need Python.\n\nAlso Go."
    assert clean_jd_text(clean_jd_text(text)) == clean_jd_text(text)


def test_collapses_runaway_blank_lines():
    out = clean_jd_text("<div></div><div></div><div></div><p>Hi</p>")
    assert "\n\n\n" not in out


def test_looks_like_html_detects_markup_and_ignores_prose():
    assert looks_like_html("<p>hello</p>")
    assert not looks_like_html("We use C++ and value x < y comparisons.")


def test_empty_input():
    assert clean_jd_text("") == ""
