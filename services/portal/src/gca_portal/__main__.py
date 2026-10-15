"""Entry point for local runs: python -m gca_portal (the image runs uvicorn gca_portal.app:app)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("gca_portal.asgi:app", host="0.0.0.0", port=8080)  # noqa: S104


if __name__ == "__main__":
    main()
