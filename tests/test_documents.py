"""Tests for the web editor's DocumentStore."""

from __future__ import annotations

from types import SimpleNamespace

from scribe.documents import DocumentStore


def make_store(tmp_path) -> DocumentStore:
    """A DocumentStore rooted entirely inside tmp_path."""
    return DocumentStore(SimpleNamespace(workspace_dir=str(tmp_path / "ws")))


def test_create_doc_and_list(tmp_path):
    store = make_store(tmp_path)
    meta = store.create("Moja beleska", "doc")

    assert meta["type"] == "doc"
    assert meta["title"] == "Moja beleska"
    listed = store.list()
    assert len(listed) == 1
    assert listed[0]["id"] == meta["id"]


def test_save_and_load_doc_content(tmp_path):
    store = make_store(tmp_path)
    meta = store.create("Beleska", "doc")
    store.save_content(meta["id"], "Prvi pasus.")

    loaded = store.load(meta["id"])
    assert loaded is not None
    assert loaded["content"] == "Prvi pasus."


def test_book_toc_and_chapters(tmp_path):
    store = make_store(tmp_path)
    book = store.create("Moja knjiga", "book")
    store.set_toc(book["id"], ["Uvod", "Razrada", "Zakljucak"])

    loaded = store.load(book["id"])
    assert loaded is not None
    assert [c["title"] for c in loaded["chapters"]] == ["Uvod", "Razrada", "Zakljucak"]

    first = loaded["chapters"][0]["id"]
    store.save_chapter(book["id"], first, "Tekst uvoda.")
    again = store.load(book["id"])
    assert again["chapters"][0]["content"] == "Tekst uvoda."


def test_set_toc_preserves_unchanged_chapter_bodies(tmp_path):
    store = make_store(tmp_path)
    book = store.create("Knjiga", "book")
    store.set_toc(book["id"], ["Uvod", "Kraj"])
    first = store.load(book["id"])["chapters"][0]["id"]
    store.save_chapter(book["id"], first, "Sadrzaj uvoda.")

    # Re-running with the same first title keeps its body.
    store.set_toc(book["id"], ["Uvod", "Sredina", "Kraj"])
    loaded = store.load(book["id"])
    titles = [c["title"] for c in loaded["chapters"]]
    assert titles == ["Uvod", "Sredina", "Kraj"]
    assert loaded["chapters"][0]["content"] == "Sadrzaj uvoda."


def test_assemble_markdown_book(tmp_path):
    store = make_store(tmp_path)
    book = store.create("Naslov", "book")
    store.set_toc(book["id"], ["Glava jedan"])
    ch_id = store.load(book["id"])["chapters"][0]["id"]
    store.save_chapter(book["id"], ch_id, "Telo glave.")

    md = store.assemble_markdown(book["id"])
    assert "# Naslov" in md
    assert "## Glava jedan" in md
    assert "Telo glave." in md


def test_assemble_epub_markdown_uses_h1_chapters(tmp_path):
    store = make_store(tmp_path)
    book = store.create("Naslov", "book")
    store.set_toc(book["id"], ["Glava jedan", "Glava dva"])
    md = store.assemble_epub_markdown(book["id"])
    # Chapters must be H1 (one EPUB section each); the book title is NOT a heading.
    assert "# Glava jedan" in md
    assert "# Glava dva" in md
    assert "# Naslov" not in md
    assert "## " not in md


def test_delete_removes_document(tmp_path):
    store = make_store(tmp_path)
    meta = store.create("Za brisanje", "doc")
    assert store.delete(meta["id"]) is True
    assert store.exists(meta["id"]) is False
    assert store.list() == []


def test_history_snapshot_and_restore(tmp_path):
    store = make_store(tmp_path)
    meta = store.create("Sa istorijom", "doc")
    did = meta["id"]

    store.save_content(did, "verzija 1")
    first = store.snapshot(did, "prva")
    store.save_content(did, "verzija 2")
    store.snapshot(did, "druga")

    history = store.list_history(did)
    assert len(history) == 2
    assert [h["label"] for h in history] == ["druga", "prva"]

    assert store.restore(did, first["ts"]) is True
    assert store.load(did)["content"] == "verzija 1"
    # Restoring snapshots the pre-restore state, so it is itself reversible.
    labels = [h["label"] for h in store.list_history(did)]
    assert "before restore" in labels


def test_export_strips_lock_sentinels(tmp_path):
    store = make_store(tmp_path)
    meta = store.create("Sa lokom", "doc")
    store.save_content(meta["id"], "Pre ⟦LOCK⟧zakljucan deo⟦/LOCK⟧ posle")

    md = store.assemble_markdown(meta["id"])
    assert "zakljucan deo" in md
    assert "⟦LOCK⟧" not in md and "⟦/LOCK⟧" not in md
