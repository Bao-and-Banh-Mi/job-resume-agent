"""Evidence-grounded resume tailoring, exposed over the Model Context Protocol.

The package is deliberately small: a Pydantic data model that mirrors
docs/data-model.md, a deterministic tailoring pipeline (no external LLM), a
LaTeX renderer that reuses the public template, and an MCP server that wires
the pipeline to five tools.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("resume-agent")
except PackageNotFoundError:  # editable install / running from source
    __version__ = "0.1.0"

__all__ = ["__version__"]
