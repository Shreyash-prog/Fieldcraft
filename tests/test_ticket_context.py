"""Ticket context (A2): a connected repo and uploaded PDFs, per tenant.

Nothing here runs an agent — this phase only attaches and stores context. The
git clone is mocked in every test, so the suite stays offline.
"""
import json

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop import github_source
from fieldcraft_loop.pdf_context import PdfContextError, PdfStore, safe_filename
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from fieldcraft_loop.ticket_store import TicketStore
from tests.conftest import ROOT

CODES = "alpha-code,beta-code"


# --- a real, minimal, text-bearing PDF ---------------------------------------

def make_pdf(lines=("Hello Fieldcraft acceptance criteria",), pages=1) -> bytes:
    """A valid one-or-more page PDF with extractable text, built by hand so the
    tests do not depend on a PDF *writer* to exercise the reader."""
    out = bytearray(b"%PDF-1.4\n")
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(pages))
    body = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i in range(pages):
        stream = "BT /F1 12 Tf 72 720 Td (" + lines[i % len(lines)] + ") Tj ET"
        body.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                    f"<< /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        body.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode())
    offsets = []
    for n, obj in enumerate(body, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(body) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(body) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def upload(client, tid, *files):
    """files: (filename, bytes) pairs."""
    return client.post(f"/api/tickets/{tid}/pdfs",
                       files=[("files", (n, d, "application/pdf")) for n, d in files])


# --- fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def context_store(tmp_path, monkeypatch):
    """Fresh ticket store, PDF store and clone root per test."""
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "pdfs", PdfStore(tmp_path / "pdfs", max_mb=10,
                                                 max_pages=200, max_per_ticket=10))
    monkeypatch.setattr(server, "TICKET_REPOS", tmp_path / "repos")
    monkeypatch.setattr(server, "CONNECTED", {})
    return tmp_path


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


@pytest.fixture
def fake_clone(monkeypatch):
    """Stand in for the network. Builds a plausible repo on disk so
    detect_test_command()/has_tests() run for real against it."""
    def _clone(url, dest, timeout_s=None, max_mb=None):
        owner, name = github_source.parse_repo_url(url)
        dest = server.Path(dest)
        (dest / "tests").mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("# demo\n")
        (dest / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n")
        return github_source.RepoInfo(owner=owner, name=name,
                                      url=github_source.clone_url_for(owner, name),
                                      path=str(dest), default_branch="main",
                                      file_count=2, size_mb=0.01)
    monkeypatch.setattr(server.github_source, "clone_public_repo", _clone)
    return _clone


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    assert c.cookies.get(COOKIE)
    return c


def make(client, **body) -> dict:
    r = client.post("/api/tickets", json={"title": "Ship the thing", **body})
    assert r.status_code == 200, r.text
    return r.json()


# =============================================================================
# connected repo
# =============================================================================

def test_connect_repo_stores_handle_and_returns_facts(fake_clone):
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/repo",
               json={"url": "https://github.com/octocat/Hello-World"})
    assert r.status_code == 200, r.text
    repo = r.json()["repo"]
    assert repo["name"] == "Hello-World" and repo["default_branch"] == "main"
    assert repo["file_count"] == 2
    assert repo["has_tests"] is True                     # computed from the clone
    assert repo["test_command"][-1] == "tests"

    after = c.get(f"/api/tickets/{t['id']}").json()
    assert after["repo_url"] == "https://github.com/octocat/Hello-World.git"
    assert after["repo_task_handle"] == repo["handle"]


def test_connect_writes_a_runnable_task_dir(fake_clone):
    """A3 will start a brief from this handle, so the task.json must be there."""
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/r"})
    tdir = server.TICKET_REPOS / "legacy" / t["id"]
    task = json.loads((tdir / "task.json").read_text())
    assert task["kind"] == "repo" and task["repo_dir"] == "repo"
    assert (tdir / "repo" / "tests" / "test_demo.py").exists()
    assert server.CONNECTED["legacy"][task["name"]] == tdir


def test_get_repo_returns_null_when_unset():
    c = TestClient(server.app)
    t = make(c)
    assert c.get(f"/api/tickets/{t['id']}/repo").json()["repo"] is None


def test_reconnect_replaces_the_previous_clone(fake_clone):
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/a/first"})
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/a/second"})
    facts = c.get(f"/api/tickets/{t['id']}/repo").json()["repo"]
    assert facts["name"] == "second"
    assert list(server.CONNECTED["legacy"]) == [facts["handle"]]   # no stale handle


def test_disconnect_clears_fields_and_removes_the_clone(fake_clone):
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/r"})
    tdir = server.TICKET_REPOS / "legacy" / t["id"]
    assert tdir.exists()

    assert c.delete(f"/api/tickets/{t['id']}/repo").status_code == 200
    assert not tdir.exists()
    after = c.get(f"/api/tickets/{t['id']}").json()
    assert after["repo_url"] is None and after["repo_task_handle"] is None
    assert c.get(f"/api/tickets/{t['id']}/repo").json()["repo"] is None
    assert server.CONNECTED["legacy"] == {}


def test_a_failed_reconnect_leaves_the_working_repo_intact(fake_clone, monkeypatch):
    """A bad second URL must not destroy the repo already attached. The first
    version cleaned up the ticket's own directory on failure, so one typo wiped a
    working clone and left the ticket pointing at a repo that was no longer there."""
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/good"})

    # a URL that never reaches git, and one whose clone fails
    assert c.post(f"/api/tickets/{t['id']}/repo",
                  json={"url": "git@github.com:o/r.git"}).status_code == 400
    monkeypatch.setattr(server.github_source, "clone_public_repo",
                        lambda *a, **k: (_ for _ in ()).throw(
                            github_source.GitHubSourceError("repository not found")))
    assert c.post(f"/api/tickets/{t['id']}/repo",
                  json={"url": "https://github.com/o/missing"}).status_code == 400

    still = c.get(f"/api/tickets/{t['id']}/repo").json()["repo"]
    assert still is not None and still["name"] == "good"
    tdir = server.TICKET_REPOS / "legacy" / t["id"]
    assert (tdir / "repo" / "tests" / "test_demo.py").exists()
    assert c.get(f"/api/tickets/{t['id']}").json()["repo_task_handle"] == still["handle"]


def test_no_staging_directories_are_left_behind(fake_clone, monkeypatch):
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/good"})
    monkeypatch.setattr(server.github_source, "clone_public_repo",
                        lambda *a, **k: (_ for _ in ()).throw(
                            github_source.GitHubSourceError("nope")))
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/bad"})
    leftovers = [p.name for p in (server.TICKET_REPOS / "legacy").iterdir()
                 if p.name.startswith(".")]
    assert leftovers == [], leftovers


@pytest.mark.parametrize("url,fragment", [
    ("git@github.com:o/r.git", "https"),
    ("https://gitlab.com/o/r", "github.com"),
    ("https://github.com/o", "owner"),
    ("https://user:pw@github.com/o/r", "credentials"),
    ("https://github.com/o/r; rm -rf /", "not allowed"),
])
def test_invalid_urls_are_refused_before_any_clone(url, fragment):
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/repo", json={"url": url})
    assert r.status_code == 400
    assert fragment in r.json()["detail"]


def test_private_or_missing_repo_surfaces_a_clear_error(monkeypatch):
    def _boom(*a, **k):
        raise github_source.GitHubSourceError(
            "repository not found — it must exist and be public "
            "(private repos are not supported)")
    monkeypatch.setattr(server.github_source, "clone_public_repo", _boom)
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/secret"})
    assert r.status_code == 400 and "public" in r.json()["detail"]
    assert not (server.TICKET_REPOS / "legacy" / t["id"]).exists()


def test_oversize_repo_is_refused_and_leaves_nothing_behind(monkeypatch):
    def _big(*a, **k):
        raise github_source.GitHubSourceError(
            "repository is 900.0 MB, over the 50.0 MB limit (FC_MAX_REPO_MB)")
    monkeypatch.setattr(server.github_source, "clone_public_repo", _big)
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/huge"})
    assert r.status_code == 400 and "FC_MAX_REPO_MB" in r.json()["detail"]
    assert not (server.TICKET_REPOS / "legacy" / t["id"]).exists()


def test_repo_on_someone_elses_ticket_is_404(secured, fake_clone):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    a.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/r"})

    assert b.post(f"/api/tickets/{t['id']}/repo",
                  json={"url": "https://github.com/o/other"}).status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/repo").status_code == 404
    assert b.delete(f"/api/tickets/{t['id']}/repo").status_code == 404
    # A's clone is untouched by B's attempts
    assert a.get(f"/api/tickets/{t['id']}/repo").json()["repo"]["name"] == "r"


def test_clones_are_namespaced_per_user(secured, fake_clone):
    a, b = session("alpha-code"), session("beta-code")
    ta, tb = make(a), make(b)
    a.post(f"/api/tickets/{ta['id']}/repo", json={"url": "https://github.com/o/r"})
    b.post(f"/api/tickets/{tb['id']}/repo", json={"url": "https://github.com/o/r"})
    roots = {p.name for p in server.TICKET_REPOS.iterdir()}
    assert len(roots) == 2 and "legacy" not in roots      # two distinct tenant trees


# =============================================================================
# PDF context
# =============================================================================

def test_upload_extracts_text_and_records_the_id():
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("spec.pdf", make_pdf()))
    assert r.status_code == 200, r.text
    docs = r.json()["pdfs"]
    assert len(docs) == 1
    assert docs[0]["filename"] == "spec.pdf" and docs[0]["pages"] == 1
    assert docs[0]["chars"] > 0 and docs[0]["id"].startswith("PDF-")
    assert "text" not in docs[0]                          # the list never carries it

    assert c.get(f"/api/tickets/{t['id']}").json()["pdf_context_ids"] == [docs[0]["id"]]


def test_extracted_text_is_stored_and_readable_only_through_the_store():
    c = TestClient(server.app)
    t = make(c)
    pid = upload(c, t["id"], ("a.pdf", make_pdf(["Redact every phone number"]))).json()["pdfs"][0]["id"]
    text = server.pdfs.stored_text("legacy", t["id"], pid)
    assert "Redact every phone number" in text


def test_multi_page_pdf_counts_pages():
    c = TestClient(server.app)
    t = make(c)
    doc = upload(c, t["id"], ("big.pdf", make_pdf(["one", "two", "three"], pages=3))).json()["pdfs"][0]
    assert doc["pages"] == 3


def test_several_files_in_one_request():
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("a.pdf", make_pdf()), ("b.pdf", make_pdf()))
    assert len(r.json()["pdfs"]) == 2 and len(r.json()["added"]) == 2


def test_a_non_pdf_is_refused_on_magic_bytes_not_extension():
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("totally.pdf", b"#!/bin/sh\nrm -rf /\n"))
    assert r.status_code == 400
    assert "not a PDF" in r.json()["detail"]
    assert c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"] == []


def test_a_pdf_header_that_does_not_parse_is_refused():
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("truncated.pdf", b"%PDF-1.4\nnot really a pdf"))
    assert r.status_code == 400
    assert c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"] == []


def test_oversize_upload_is_refused(monkeypatch):
    monkeypatch.setattr(server.settings, "max_pdf_mb", 0.001)     # ~1 KB
    monkeypatch.setattr(server, "pdfs", PdfStore(server.pdfs.root, max_mb=0.001))
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("fat.pdf", make_pdf(["x" * 4000])))
    assert r.status_code == 400 and "FC_MAX_PDF_MB" in r.json()["detail"]


def test_page_cap_is_enforced(monkeypatch):
    monkeypatch.setattr(server, "pdfs", PdfStore(server.pdfs.root, max_pages=2))
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("long.pdf", make_pdf(["a", "b", "c", "d"], pages=4)))
    assert r.status_code == 400 and "page limit" in r.json()["detail"]


def test_per_ticket_count_cap(monkeypatch):
    monkeypatch.setattr(server, "pdfs", PdfStore(server.pdfs.root, max_per_ticket=2))
    c = TestClient(server.app)
    t = make(c)
    assert upload(c, t["id"], ("a.pdf", make_pdf())).status_code == 200
    assert upload(c, t["id"], ("b.pdf", make_pdf())).status_code == 200
    r = upload(c, t["id"], ("c.pdf", make_pdf()))
    assert r.status_code == 400 and "limit 2" in r.json()["detail"]
    assert len(c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"]) == 2


def test_a_rejected_file_rolls_back_the_whole_request():
    """A batch is all-or-nothing: the good file in front of a bad one must not
    survive, or the caller has no idea what actually landed."""
    c = TestClient(server.app)
    t = make(c)
    r = upload(c, t["id"], ("good.pdf", make_pdf()), ("bad.pdf", b"nope"))
    assert r.status_code == 400 and "bad.pdf" in r.json()["detail"]
    assert c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"] == []
    assert c.get(f"/api/tickets/{t['id']}").json()["pdf_context_ids"] == []


def test_list_and_delete():
    c = TestClient(server.app)
    t = make(c)
    ids = [d["id"] for d in upload(c, t["id"], ("a.pdf", make_pdf()),
                                   ("b.pdf", make_pdf())).json()["pdfs"]]
    assert {d["id"] for d in c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"]} == set(ids)

    r = c.delete(f"/api/tickets/{t['id']}/pdfs/{ids[0]}")
    assert r.status_code == 200
    assert [d["id"] for d in r.json()["pdfs"]] == [ids[1]]
    assert c.get(f"/api/tickets/{t['id']}").json()["pdf_context_ids"] == [ids[1]]


def test_deleting_an_unknown_pdf_is_404():
    c = TestClient(server.app)
    t = make(c)
    assert c.delete(f"/api/tickets/{t['id']}/pdfs/PDF-nope").status_code == 404


def test_pdf_id_cannot_traverse_out_of_the_ticket_directory():
    c = TestClient(server.app)
    t = make(c)
    upload(c, t["id"], ("a.pdf", make_pdf()))
    assert c.delete(f"/api/tickets/{t['id']}/pdfs/..%2F..%2Fetc").status_code == 404
    assert len(c.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"]) == 1


def test_pdfs_on_someone_elses_ticket_are_404(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    pid = upload(a, t["id"], ("secret-spec.pdf", make_pdf())).json()["pdfs"][0]["id"]

    assert upload(b, t["id"], ("mine.pdf", make_pdf())).status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/pdfs").status_code == 404
    assert b.delete(f"/api/tickets/{t['id']}/pdfs/{pid}").status_code == 404
    assert len(a.get(f"/api/tickets/{t['id']}/pdfs").json()["pdfs"]) == 1


def test_pdf_storage_is_namespaced_per_user(secured):
    a, b = session("alpha-code"), session("beta-code")
    ta, tb = make(a), make(b)
    upload(a, ta["id"], ("a.pdf", make_pdf()))
    upload(b, tb["id"], ("b.pdf", make_pdf()))
    roots = {p.name for p in server.pdfs.root.iterdir()}
    assert len(roots) == 2 and "legacy" not in roots


def test_deleting_the_ticket_drops_its_context(fake_clone):
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/repo", json={"url": "https://github.com/o/r"})
    upload(c, t["id"], ("a.pdf", make_pdf()))
    assert c.delete(f"/api/tickets/{t['id']}").status_code == 200
    assert not (server.TICKET_REPOS / "legacy" / t["id"]).exists()
    assert server.pdfs.list_for("legacy", t["id"]) == []


# --- store-level guards ------------------------------------------------------

def test_safe_filename_strips_paths_and_control_characters():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("a\x00b.pdf") == "ab.pdf"
    assert safe_filename("") == "document.pdf"
    assert len(safe_filename("x" * 500)) <= 120


def test_store_rejects_identifiers_that_are_not_ids(tmp_path):
    store = PdfStore(tmp_path)
    with pytest.raises(PdfContextError):
        store.add("../escape", "TCK-1", "a.pdf", make_pdf())
    with pytest.raises(PdfContextError):
        store.add("u-1", "../escape", "a.pdf", make_pdf())


def test_encrypted_pdfs_are_refused(tmp_path):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    import io
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.encrypt("hunter2")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(PdfContextError, match="encrypted"):
        PdfStore(tmp_path).add("u-1", "TCK-1", "locked.pdf", buf.getvalue())


# --- packaging: the dependency has to reach the image ------------------------

def test_pdf_dependencies_are_importable():
    """Both are runtime requirements of the upload route. python-multipart is the
    easy one to miss: FastAPI only raises on the first multipart request."""
    import python_multipart                                 # noqa: F401
    import pypdf                                            # noqa: F401


def test_pdf_dependencies_are_declared_in_requirements():
    """The Dockerfile installs requirements.txt and nothing else, so a dependency
    that is only in the dev venv ships an image whose upload route 500s."""
    req = (ROOT / "requirements.txt").read_text().lower()
    assert "pypdf" in req, "pypdf missing from requirements.txt"
    assert "python-multipart" in req, "python-multipart missing from requirements.txt"
