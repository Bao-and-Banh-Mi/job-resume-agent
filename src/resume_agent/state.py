"""Process-local session state for the MCP server.

Kept intentionally simple: two dicts and a pointer to the currently-active
JD. No persistence. A future Chrome extension will hit the MCP tools per
session, and the review UI will keep authoritative state on the client.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import threading
from typing import Optional

from .models import Draft, ExperienceBank, JobDescription


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bank: Optional[ExperienceBank] = None
        self._bank_path: Optional[str] = None
        self._jobs: dict[str, JobDescription] = {}
        self._drafts: dict[str, Draft] = {}
        self._active_job_id: Optional[str] = None

    # --- bank ---------------------------------------------------------------

    def set_bank(self, bank: ExperienceBank, path: str) -> None:
        with self._lock:
            self._bank = bank
            self._bank_path = path

    def bank(self) -> ExperienceBank:
        with self._lock:
            if self._bank is None:
                raise RuntimeError(
                    "experience bank not loaded; set RESUME_AGENT_BANK_PATH or "
                    "call load_bank() before invoking tailoring tools"
                )
            return self._bank

    def bank_path(self) -> str:
        with self._lock:
            return self._bank_path or ""

    # --- jobs ---------------------------------------------------------------

    def new_job_id(self, jd_text: str) -> str:
        stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
        h = hashlib.sha1((stamp + jd_text[:2048]).encode("utf-8")).hexdigest()[:12]
        return f"job-{h}"

    def put_job(self, job: JobDescription) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id

    def get_job(self, job_id: str) -> JobDescription:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"unknown job_id: {job_id}")
            return self._jobs[job_id]

    def active_job_id(self) -> Optional[str]:
        with self._lock:
            return self._active_job_id

    # --- drafts -------------------------------------------------------------

    def put_draft(self, draft: Draft) -> None:
        with self._lock:
            self._drafts[draft.draft_id] = draft

    def get_draft(self, draft_id: str) -> Draft:
        with self._lock:
            if draft_id not in self._drafts:
                raise KeyError(f"unknown draft_id: {draft_id}")
            return self._drafts[draft_id]

    def replace_draft(self, draft: Draft) -> None:
        with self._lock:
            self._drafts[draft.draft_id] = draft
