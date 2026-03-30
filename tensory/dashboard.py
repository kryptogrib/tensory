"""tensory-dashboard — one-command web dashboard for Tensory memory.

Serves the FastAPI dashboard API + Next.js static UI on a single port.
Uses the same SQLite database as the MCP server.

Usage::

    tensory-dashboard                          # defaults: :8000, data/tensory.db
    tensory-dashboard --port 3000              # custom port
    tensory-dashboard --db ./my-agent.db       # custom DB path
    TENSORY_DB_PATH=./mem.db tensory-dashboard # env var also works

Requires ``tensory[ui]`` extra: ``uv add tensory[ui]``
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser


def main() -> None:
    """Entry point for ``tensory-dashboard`` CLI command."""
    parser = argparse.ArgumentParser(
        prog="tensory-dashboard",
        description="Launch the Tensory memory dashboard (API + UI).",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.getenv("TENSORY_DASHBOARD_PORT", "8000")),
        help="Port to serve on (default: 8000)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=os.getenv("TENSORY_DB_PATH", os.getenv("TENSORY_DB", "data/tensory.db")),
        help="Path to SQLite database (default: data/tensory.db)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't auto-open browser",
    )
    args = parser.parse_args()

    # Set DB path for api/main.py lifespan
    os.environ["TENSORY_DB_PATH"] = args.db

    # Ensure api/ package is importable
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        import uvicorn
    except ImportError:
        print("Dashboard requires fastapi and uvicorn.")
        print("Install with: uv add tensory[ui]")
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"
    print(f"Tensory Dashboard: {url}")
    print(f"Database: {args.db}")
    print("Press Ctrl+C to stop.\n")

    if not args.no_open:
        webbrowser.open(url)

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
