"""Document API: upload, detect, produce three redacted versions, download."""

import re
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .detect.employees import EmployeeDirectory
from .detect.ner import NerDetector
from .detect.pipeline import detect
from .models import Finding, Version
from .policy import suggest_label
from .redact.docx import extract_docx_text, redact_docx
from .redact.pdf import DocumentError, extract_pdf_text, redact_pdf

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXT = (".pdf", ".docx")
VERSIONS = ("publik", "internal", "rahasia")
DOC_ERROR = "Dokumen terenkripsi atau rusak. Buka kunci atau simpan ulang file, lalu upload lagi."
_ID = re.compile(r"^[0-9a-f]{32}$")


def create_app(ner: NerDetector, directory: EmployeeDirectory, storage: Path) -> FastAPI:
    app = FastAPI(title="DigitaDLP")
    storage = Path(storage)

    def doc_dir(doc_id: str) -> Path:
        if not _ID.fullmatch(doc_id):
            raise HTTPException(404, "Dokumen tidak ditemukan.")
        d = storage / doc_id
        if not d.is_dir():
            raise HTTPException(404, "Dokumen tidak ditemukan.")
        return d

    def source_of(d: Path) -> Path:
        for ext in ALLOWED_EXT:
            p = d / f"source{ext}"
            if p.is_file():
                return p
        raise HTTPException(404, "Dokumen tidak ditemukan.")

    def run_detect(d: Path) -> list[list[Finding]]:
        src = source_of(d)
        pages = extract_pdf_text(src) if src.suffix == ".pdf" else extract_docx_text(src)
        return [detect(t, ner, directory) for t in pages]

    @app.post("/documents", status_code=201)
    async def upload(file: UploadFile = File(...)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(415, "Hanya file PDF atau DOCX yang didukung.")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Ukuran file melebihi batas 50 MB.")
        doc_id = uuid.uuid4().hex
        d = storage / doc_id
        d.mkdir(parents=True)
        try:
            (d / f"source{ext}").write_bytes(data)
            per_page = run_detect(d)
        except DocumentError:
            shutil.rmtree(d, ignore_errors=True)
            raise HTTPException(422, DOC_ERROR) from None
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        findings = [f for page in per_page for f in page]
        return {
            "id": doc_id,
            "suggested_label": suggest_label(findings).value,
            "findings": [
                {"kind": f.kind.value, "text": f.text, "start": f.start, "end": f.end, "page": i}
                for i, page in enumerate(per_page)
                for f in page
            ],
        }

    @app.post("/documents/{doc_id}/versions")
    def make_versions(doc_id: str):
        d = doc_dir(doc_id)
        src = source_of(d)
        ext = src.suffix
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=d))
        try:
            per_page = run_detect(d)
            for v in VERSIONS:
                dst = tmp / f"{v}{ext}"
                if ext == ".pdf":
                    redact_pdf(src, dst, per_page, Version(v))
                else:
                    redact_docx(src, dst, lambda t: detect(t, ner, directory), Version(v))
            for v in VERSIONS:
                (tmp / f"{v}{ext}").replace(d / f"{v}{ext}")
        except DocumentError:
            raise HTTPException(422, DOC_ERROR) from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"versions": list(VERSIONS)}

    @app.get("/documents/{doc_id}/versions/{version}")
    def get_version(doc_id: str, version: str):
        d = doc_dir(doc_id)
        if version not in VERSIONS:
            raise HTTPException(404, "Versi tidak ditemukan.")
        p = d / f"{version}{source_of(d).suffix}"
        if not p.is_file():
            raise HTTPException(404, "Versi belum dibuat.")
        return FileResponse(p, filename=f"{version}{p.suffix}")

    return app
