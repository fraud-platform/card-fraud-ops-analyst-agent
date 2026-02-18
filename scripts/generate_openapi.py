"""Generate OpenAPI specification from FastAPI app.

Usage:
    python scripts/generate_openapi.py [--output docs/03-api/openapi.json]

This script generates the OpenAPI 3.1 specification for the Card Fraud Ops
Analyst Agent API and writes it to the specified output path.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import create_app


def generate_openapi(output_path: str = "docs/03-api/openapi.json") -> dict:
    """Generate and save OpenAPI specification."""
    app = create_app()
    openapi_spec = app.openapi()

    # Add metadata
    openapi_spec["info"]["x-generated-at"] = datetime.now(UTC).isoformat()

    # Ensure output directory exists
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(openapi_spec, f, indent=2)

    print(f"OpenAPI spec written to: {output_path}")
    return openapi_spec


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/03-api/openapi.json"
    generate_openapi(output)
