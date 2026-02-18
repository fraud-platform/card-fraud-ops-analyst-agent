"""Run development server."""


def main() -> None:
    """Start the dev server via uvicorn."""
    from app.main import run

    run()


if __name__ == "__main__":
    main()
