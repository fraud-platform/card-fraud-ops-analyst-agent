"""CLI wrapper: generate OpenAPI spec."""

from cli._runner import run


def main() -> None:
    """Generate OpenAPI spec."""
    import sys

    sys.exit(run(["uv", "run", "python", "scripts/generate_openapi.py"]))
