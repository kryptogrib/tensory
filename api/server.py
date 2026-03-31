"""CLI entry point for ``tensory-server`` command.

Starts the FastAPI server (API + dashboard UI) via uvicorn.
Usage: tensory-server [--host HOST] [--port PORT]
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    """Launch the Tensory dashboard server."""
    parser = argparse.ArgumentParser(description="Tensory Dashboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8888, help="Port (default: 8888)")
    parser.add_argument("--db", default=None, help="Database path (default: data/tensory.db)")
    args = parser.parse_args()

    if args.db:
        os.environ["TENSORY_DB_PATH"] = os.path.expanduser(args.db)

    import uvicorn

    uvicorn.run("api.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
