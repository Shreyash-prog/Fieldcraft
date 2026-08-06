"""PDF context attached to a ticket — validated, extracted once, stored per tenant.

A ticket's context documents (specs, design docs, acceptance criteria) are
uploaded as PDFs, their text is extracted at upload time, and the text is what
later phases will read. Extraction happens once so the run phase never re-parses
a binary, and so an unparseable file fails at upload — while a human is watching
— rather than mid-run.

Everything here fails **closed**. A file must be under the size cap, start with
the PDF magic bytes, parse, be unencrypted, and be within the page cap before a
single byte is written to disk. Extension and client-supplied content-type are
not evidence of anything and are never trusted.

Storage is `<root>/<user_id>/<ticket_id>/<pdf_id>.json`. Both id components are
validated against a strict pattern before they touch a path, so a crafted
ticket id cannot escape the tenant's directory.

SECURITY — the extracted text is UNTRUSTED INPUT (HARDENING.md P0-5)
--------------------------------------------------------------------
A PDF is attacker-supplied content. Its text can contain prompt-injection
("ignore previous instructions", fake tool output, fake system messages) aimed
at whatever model eventually reads it. In this phase (A2) the text is only
stored and listed back to the uploader — it is **not** fed to any agent, judge
or prompt.

TODO(A3/Phase B): before this text reaches a prompt it MUST be treated as
untrusted per P0-5 — tagged with its provenance (filename + "user-uploaded
PDF"), delimited so it cannot be confused with instructions, and never granted
authority to change the task, the policy, or the tool surface. Do not
concatenate it into a system prompt. See `stored_text()`, which is deliberately
the only reader and carries the same warning.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

# A PDF must start with this; anything else is not a PDF whatever it is named.
MAGIC = b"%PDF-"
# ids we generate, and the only shape accepted back from a caller
_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
FILENAME_MAX = 120
# a per-document text ceiling, so one pathological PDF cannot fill the disk
TEXT_MAX_CHARS = 400_000


class PdfContextError(Exception):
    """An upload rejected on purpose — too big, not a PDF, encrypted, over caps."""


@dataclass
class PdfMeta:
    id: str
    filename: str
    pages: int
    chars: int
    bytes: int
    created_at: float
    truncated: bool = False


def safe_filename(name: str | None) -> str:
    """Strip every path component and control character. Never used to build a
    path — storage is keyed by generated id — but it is echoed back to the UI."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or "document.pdf")[:FILENAME_MAX]


def _extract(data: bytes, max_pages: int) -> tuple[int, str]:
    """(page_count, text). Raises PdfContextError for anything unreadable."""
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as e:      # pragma: no cover - packaging guard
        raise PdfContextError(
            "PDF support is not installed on this server (pypdf)") from e

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise PdfContextError(f"could not read that PDF ({type(e).__name__})") from e

    if getattr(reader, "is_encrypted", False):
        raise PdfContextError("encrypted PDFs are not supported — remove the password first")

    pages = len(reader.pages)
    if pages == 0:
        raise PdfContextError("that PDF has no pages")
    if pages > max_pages:
        raise PdfContextError(f"{pages} pages is over the {max_pages}-page limit")

    out: list[str] = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")                 # one bad page must not sink the upload
    return pages, "\n".join(out).strip()


class PdfStore:
    """Per-tenant PDF context. Every method takes the owning user_id; nothing
    here is reachable across tenants because the path starts with it."""

    def __init__(self, root: str | Path, max_mb: float = 10.0,
                 max_pages: int = 200, max_per_ticket: int = 10):
        self.root = Path(root)
        self.max_mb = float(max_mb)
        self.max_pages = int(max_pages)
        self.max_per_ticket = int(max_per_ticket)

    # -- paths -------------------------------------------------------------
    def _dir(self, user_id: str, ticket_id: str) -> Path:
        for part in (user_id, ticket_id):
            if not _ID.match(part or ""):
                raise PdfContextError("invalid identifier")
        return self.root / user_id / ticket_id

    # -- writes ------------------------------------------------------------
    def add(self, user_id: str, ticket_id: str, filename: str, data: bytes) -> dict:
        """Validate, extract, store. Raises PdfContextError before writing
        anything if the upload does not pass every check."""
        d = self._dir(user_id, ticket_id)

        if not data:
            raise PdfContextError("that file is empty")
        limit = int(self.max_mb * 1024 * 1024)
        if len(data) > limit:
            raise PdfContextError(
                f"{round(len(data)/1048576, 2)} MB is over the {self.max_mb} MB "
                "limit (FC_MAX_PDF_MB)")
        # Magic bytes, not the extension or the browser's content-type.
        if not data.startswith(MAGIC):
            raise PdfContextError("that file is not a PDF (missing %PDF- header)")

        existing = self.list_for(user_id, ticket_id)
        if len(existing) >= self.max_per_ticket:
            raise PdfContextError(
                f"this ticket already has {len(existing)} PDFs "
                f"(limit {self.max_per_ticket})")

        pages, text = _extract(data, self.max_pages)
        truncated = len(text) > TEXT_MAX_CHARS
        if truncated:
            text = text[:TEXT_MAX_CHARS]

        meta = PdfMeta(id="PDF-" + uuid.uuid4().hex[:10],
                       filename=safe_filename(filename), pages=pages,
                       chars=len(text), bytes=len(data), created_at=time.time(),
                       truncated=truncated)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{meta.id}.tmp"
        tmp.write_text(json.dumps({**asdict(meta), "text": text}))
        tmp.rename(d / f"{meta.id}.json")   # atomic: a reader never sees a partial file
        return asdict(meta)

    def delete(self, user_id: str, ticket_id: str, pdf_id: str) -> bool:
        if not _ID.match(pdf_id or ""):
            return False
        p = self._dir(user_id, ticket_id) / f"{pdf_id}.json"
        if not p.is_file():
            return False
        p.unlink()
        return True

    def delete_ticket(self, user_id: str, ticket_id: str) -> None:
        """Drop every PDF for a ticket (called when the ticket itself goes)."""
        shutil.rmtree(self._dir(user_id, ticket_id), ignore_errors=True)

    # -- reads -------------------------------------------------------------
    def list_for(self, user_id: str, ticket_id: str) -> list[dict]:
        d = self._dir(user_id, ticket_id)
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.glob("PDF-*.json")):
            try:
                doc = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            doc.pop("text", None)           # the list never carries the payload
            out.append(doc)
        out.sort(key=lambda m: m.get("created_at", 0))
        return out

    def stored_text(self, user_id: str, ticket_id: str, pdf_id: str) -> str | None:
        """The extracted text.

        SECURITY: this is UNTRUSTED, user-supplied content (HARDENING.md P0-5).
        Nothing in A2 calls this. When A3 does, it must delimit the text, tag its
        provenance, and treat any instructions inside it as data — never as
        instructions to the agent.
        """
        if not _ID.match(pdf_id or ""):
            return None
        p = self._dir(user_id, ticket_id) / f"{pdf_id}.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text()).get("text", "")
        except (OSError, ValueError):
            return None
