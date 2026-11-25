import os
import stat

import pytest
from cryptography.fernet import Fernet

from digitadlp.app.storage import FileStore, StoreError

DOC = "a" * 32
NIK = b"6474015203880002"


@pytest.fixture
def key():
    return Fernet.generate_key().decode()


@pytest.fixture
def store(tmp_path, key):
    return FileStore(tmp_path / "files", key)


def test_roundtrip(store):
    assert not store.exists(DOC, "source.pdf")
    store.put(DOC, "source.pdf", b"isi " + NIK)
    assert store.exists(DOC, "source.pdf")
    assert store.get(DOC, "source.pdf") == b"isi " + NIK


def test_put_file(store, tmp_path):
    p = tmp_path / "x.docx"
    p.write_bytes(b"halo")
    store.put_file(DOC, "rahasia.docx", p)
    assert store.get(DOC, "rahasia.docx") == b"halo"


def test_on_disk_is_not_plaintext(store, tmp_path):
    store.put(DOC, "source.pdf", b"NIK " + NIK)
    files = [f for f in (tmp_path / "files").rglob("*") if f.is_file()]
    assert files and all(f.name.endswith(".enc") for f in files)
    for f in files:
        assert NIK not in f.read_bytes()


@pytest.mark.parametrize("name", ["../x", "source.txt", "publik", "x/source.pdf", "SOURCE.pdf"])
def test_bad_name_rejected(store, name):
    with pytest.raises(ValueError):
        store.put(DOC, name, b"x")
    with pytest.raises(ValueError):
        store.get(DOC, name)
    with pytest.raises(ValueError):
        store.exists(DOC, name)


@pytest.mark.parametrize("doc", ["../" + "a" * 29, "abc", "G" * 32, "A" * 32, ("a" * 31) + "\n"])
def test_bad_doc_id_rejected(store, doc):
    with pytest.raises(ValueError):
        store.put(doc, "source.pdf", b"x")
    with pytest.raises(ValueError):
        store.delete_versions(doc)


def test_bad_key_rejected(tmp_path):
    with pytest.raises(ValueError, match="enkripsi"):
        FileStore(tmp_path, "bukan-kunci")
    with pytest.raises(ValueError):
        FileStore(tmp_path, "")


def test_decrypted_content_mode_and_suffix(store, tmp_path):
    store.put(DOC, "publik.docx", b"abc")
    with store.decrypted(DOC, "publik.docx") as p:
        assert p.suffix == ".docx"
        assert p.read_bytes() == b"abc"
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
        assert p.parent == (tmp_path / "files" / ".tmp")
        assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700
        assert "publik" not in p.name and DOC not in p.name
    assert not p.exists()


def test_decrypted_tempfile_removed_on_error(store):
    store.put(DOC, "source.pdf", b"abc")
    seen = []
    with pytest.raises(RuntimeError):
        with store.decrypted(DOC, "source.pdf") as p:
            seen.append(p)
            assert p.exists()
            raise RuntimeError("boom")
    assert not seen[0].exists()


def test_wrong_key_raises(store, tmp_path):
    store.put(DOC, "source.pdf", b"abc")
    other = FileStore(tmp_path / "files", Fernet.generate_key().decode())
    with pytest.raises(StoreError, match="File tidak bisa dibuka"):
        other.get(DOC, "source.pdf")
    with pytest.raises(StoreError):
        with other.decrypted(DOC, "source.pdf"):
            pass


def test_get_missing_raises_store_error(store):
    with pytest.raises(StoreError):
        store.get(DOC, "source.pdf")


def test_delete_versions(store):
    for n in ["source.pdf", "publik.pdf", "internal.docx", "rahasia.pdf"]:
        store.put(DOC, n, b"x")
    store.delete_versions(DOC)
    assert store.exists(DOC, "source.pdf")
    for n in ["publik.pdf", "internal.docx", "rahasia.pdf"]:
        assert not store.exists(DOC, n)
    store.delete_versions(DOC)  # idempotent


def test_put_overwrites_atomically(store, tmp_path):
    store.put(DOC, "source.pdf", b"1")
    store.put(DOC, "source.pdf", b"2")
    assert store.get(DOC, "source.pdf") == b"2"
    assert [f.name for f in (tmp_path / "files" / DOC).iterdir()] == ["source.pdf.enc"]


def test_init_purges_leftover_tmp(tmp_path, key):
    tmp = tmp_path / "files" / ".tmp"
    tmp.mkdir(parents=True)
    (tmp / "sisa.pdf").write_bytes(NIK)
    FileStore(tmp_path / "files", key)
    assert list(tmp.iterdir()) == []


def test_purge_tmp_older_than(store, tmp_path):
    tmp = tmp_path / "files" / ".tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    old, new = tmp / "old.pdf", tmp / "new.pdf"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    past = old.stat().st_mtime - 7200
    os.utime(old, (past, past))
    assert store.purge_tmp(older_than_seconds=3600) == 1
    assert not old.exists() and new.exists()
