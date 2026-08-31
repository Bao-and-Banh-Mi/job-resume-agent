"""Turn a raw job-posting capture into clean plain text.

Job descriptions arrive as scraped HTML (Greenhouse, Lever, Ashby, Workday)
or as pasted text. The agent reasoning over the posting should never see
markup, script/style bodies, or navigation chrome -- those cost tokens and
actively mislead. This module is the single normalisation point.

It deliberately does NOT extract "requirements". Deciding what a posting
actually asks for is a judgement call, and the caller of this MCP server is
a language model that is far better at it than any regex. The server's job
is to hand over clean text; the model's job is to read it.
"""

from __future__ import annotations

import html
import re

# Elements whose *contents* are never human-readable posting copy.
_DROP_ELEMENTS = ("script", "style", "noscript", "svg", "head", "iframe")

# Block-level tags that should become a line break rather than running two
# sentences together when the tags are stripped.
_BLOCK_TAGS = (
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
)


def looks_like_html(text: str) -> bool:
    """Heuristic: does this capture still contain markup?"""
    return bool(re.search(r"<(?:/?)(?:p|div|br|li|ul|span|h[1-6]|script)\b", text, re.I))


def clean_jd_text(raw: str) -> str:
    """Normalise a raw JD capture to readable plain text.

    Idempotent: running it on already-clean text returns that text with
    whitespace tidied, so callers never need to guess whether to call it.
    """
    if not raw:
        return ""

    text = raw

    if looks_like_html(text):
        # 1. Remove elements whose contents are not posting copy.
        for tag in _DROP_ELEMENTS:
            text = re.sub(
                rf"<{tag}\b[^>]*>.*?</{tag}>", " ", text, flags=re.I | re.S
            )
            # Unclosed variants (common in truncated scrapes).
            text = re.sub(rf"<{tag}\b[^>]*/?>", " ", text, flags=re.I)

        # 2. HTML comments.
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)

        # 3. Block tags become newlines so structure survives stripping.
        for tag in _BLOCK_TAGS:
            text = re.sub(rf"</?{tag}\b[^>]*>", "\n", text, flags=re.I)

        # 4. Every other tag disappears without joining words together.
        text = re.sub(r"<[^>]+>", " ", text)

    # 5. Entities: &amp; -> &, &nbsp; -> space, numeric refs, etc.
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("\u200b", "")

    # 6. Collapse whitespace. Preserve paragraph structure (blank lines) but
    #    kill the runs of empty lines that tag-stripping produces.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
