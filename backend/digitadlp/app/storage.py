"""Penyimpanan file terenkripsi (Fernet) di disk lokal."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

_DOC_ID = re.compile(r"[0-9a-f]{32}")
_NAME = re.compile(r"(source|publik|internal|rahasia)\.(pdf|docx)")
_VERSIONS = ("publik", "internal", "rahasia")
_EXTS = ("pdf", "docx")
_LEGACY_BLOBS = ("employees.xlsx",)
_CONFIG_DIR = "_config"


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
        # Sisa file terdekripsi dari proses yang crash tidak boleh tertinggal.
        self.purge_tmp(older_than_seconds=0)
        self.delete_legacy_blobs()

    def delete_legacy_blobs(self) -> None:
        """Hapus file konfigurasi lama (mis. daftar pegawai terenkripsi) bila ada."""
        for name in _LEGACY_BLOBS:
            try:
                (self.root / _CONFIG_DIR / (name + ".enc")).unlink()
            except FileNotFoundError:
                pass

    def _path(self, doc_id: str, name: str) -> Path:
        _check(doc_id, name)
        return self.root / doc_id / (name + ".enc")

    def put(self, doc_id: str, name: str, data: bytes) -> None:
        self._write(self._path(doc_id, name), data)

    def _write(self, path: Path, data: bytes) -> None:
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
        return self._decrypt(self._path(doc_id, name))

    def _decrypt(self, path: Path) -> bytes:
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

    def delete_source(self, doc_id: str, keep: str | None = None) -> None:
        """Hapus source.* kecuali ekstensi `keep`."""
        _check(doc_id)
        for ext in _EXTS:
            if ext != keep:
                try:
                    self._path(doc_id, f"source.{ext}").unlink()
                except FileNotFoundError:
                    pass

    def delete_versions(self, doc_id: str) -> None:
        _check(doc_id)
        for v in _VERSIONS:
            for ext in _EXTS:
                try:
                    self._path(doc_id, f"{v}.{ext}").unlink()
                except FileNotFoundError:
                    pass

    def purge_tmp(self, older_than_seconds: int = 3600) -> int:
        """Hapus file sementara di root/.tmp yang lebih tua dari batas. Mengembalikan jumlah terhapus."""
        tmpdir = self.root / ".tmp"
        if not tmpdir.is_dir():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for f in tmpdir.iterdir():
            try:
                if not (older_than_seconds <= 0 or f.stat().st_mtime <= cutoff):
                    continue
                if f.is_dir() and not f.is_symlink():
                    shutil.rmtree(f, ignore_errors=True)
                    removed += 1
                elif f.is_file() or f.is_symlink():
                    f.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
        return removed

    @contextmanager
    def scratch_dir(self) -> Iterator[Path]:
        """Direktori sementara 0700 di root/.tmp; dihapus saat keluar."""
        tmpdir = self.root / ".tmp"
        tmpdir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(tmpdir, 0o700)
        path = Path(tempfile.mkdtemp(dir=tmpdir, prefix="scratch-"))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

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
