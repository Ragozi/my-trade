"""Run the My-Trade operator API (FastAPI + uvicorn).

Serves the Lovable frontend at http://localhost:8000 by default.
Run with:  python -m scripts.api_server   (or: poe api)
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    import uvicorn

    from my_trade.api import app

    host = "127.0.0.1"
    port = int(__import__("os").environ.get("API_PORT", "8000"))
    print(f"\n  My-Trade API at http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
