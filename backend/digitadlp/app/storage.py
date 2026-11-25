"""Penyimpanan file terenkripsi (Fernet) di disk lokal."""
from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

_DOC_ID = re.compile(r"[0-9a-f]{32}")
_NAME = re.compile(r"(source|publik|internal|rahasia)\.(pdf|docx)")
_VERSIONS = ("publik", "internal", "rahasia")
_EXTS = ("pdf", "docx")


class StoreError(Exception):
    pass


def _check(doc_id: str, name: str | None = None) -> None:
    if not isinstance(doc_id, str) or not _DOC_ID.fullmatch(doc_id):
        raise ValueError("ID dokumen tidak valid.")
    if name is not None and (not isinstance(name, str) or not _NAME.fullmatch(name)):
        raise ValueError("Nama file tidak valid.")


class FileStore:
    def __init__(self, root: Path, fernet_key: str):
        try:
            self._fernet = Fernet(fernet_key)
        except (ValueError, TypeError):
            raise ValueError(
                "Kunci enkripsi tidak valid. Gunakan kunci Fernet (base64 32 byte)."
            ) from None
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, doc_id: str, name: str) -> Path:
        _check(doc_id, name)
        return self.root / doc_id / (name + ".enc")

    def put(self, doc_id: str, name: str, data: bytes) -> None:
        path = self._path(doc_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        token = self._fernet.encrypt(data)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".w", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(token)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    def put_file(self, doc_id: str, name: str, path: Path) -> None:
        self.put(doc_id, name, Path(path).read_bytes())

    def get(self, doc_id: str, name: str) -> bytes:
        path = self._path(doc_id, name)
        try:
            token = path.read_bytes()
        except FileNotFoundError:
            raise StoreError("File tidak ditemukan.") from None
        try:
            return self._fernet.decrypt(token)
        except InvalidToken:
            raise StoreError(
                "File tidak bisa dibuka. Kunci enkripsi tidak cocok atau file rusak."
            ) from None

    def exists(self, doc_id: str, name: str) -> bool:
        return self._path(doc_id, name).is_file()

    def delete_versions(self, doc_id: str) -> None:
        _check(doc_id)
        for v in _VERSIONS:
            for ext in _EXTS:
                try:
                    self._path(doc_id, f"{v}.{ext}").unlink()
                except FileNotFoundError:
                    pass

    @contextmanager
    def decrypted(self, doc_id: str, name: str) -> Iterator[Path]:
        data = self.get(doc_id, name)
        tmpdir = self.root / ".tmp"
        tmpdir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(tmpdir, 0o700)
        fd, tmp = tempfile.mkstemp(dir=tmpdir, suffix=Path(name).suffix)
        path = Path(tmp)
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            yield path
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
