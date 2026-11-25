"""Entry point: `python -m digitadlp` (satu proses, worker bawaan).

Sama dengan `uvicorn digitadlp.app.main:app --workers 1`.
"""

import os

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "digitadlp.app.main:app",
        host=os.environ.get("DIGITADLP_HOST", "127.0.0.1"),
        port=int(os.environ.get("DIGITADLP_PORT", "8000")),
        workers=1,
    )
