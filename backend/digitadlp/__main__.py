"""Entry point: `python -m digitadlp` or `uvicorn digitadlp.__main__:app`."""

import os
from pathlib import Path

from .api import create_app
from .detect.employees import EmployeeDirectory
from .detect.ner import FakeNer


def build_app():
    if os.environ.get("DIGITADLP_NER") == "fake":
        # Dev/test only: no model, so name detection is effectively off.
        ner = FakeNer({})
    else:
        from .detect.ner import IndoBertNer

        model_path = os.environ.get("DIGITADLP_NER_PATH")
        if not model_path:
            raise RuntimeError(
                "DIGITADLP_NER_PATH belum diatur (folder model IndoBERT NER). "
                "Untuk dev/test tanpa model: DIGITADLP_NER=fake."
            )
        ner = IndoBertNer(model_path)
    xlsx = os.environ.get("DIGITADLP_EMPLOYEES_XLSX")
    directory = EmployeeDirectory.from_xlsx(xlsx) if xlsx else EmployeeDirectory.from_names([])
    storage = Path(os.environ.get("DIGITADLP_STORAGE", "./storage"))
    storage.mkdir(parents=True, exist_ok=True)
    return create_app(ner, directory, storage)


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
