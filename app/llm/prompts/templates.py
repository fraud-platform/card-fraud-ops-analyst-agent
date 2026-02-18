"""Prompt template management."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptTemplate:
    """Immutable prompt template."""

    name: str
    version: str
    system_prompt: str
    user_template: str


class PromptRegistry:
    """Versioned template store."""

    def __init__(self):
        self._templates: dict[tuple[str, str], PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> None:
        """Register a template."""
        key = (template.name, template.version)
        self._templates[key] = template

    def get(self, name: str, version: str) -> PromptTemplate | None:
        """Get template by name and version."""
        key = (name, version)
        return self._templates.get(key)

    def list_versions(self, name: str) -> list[str]:
        """List all versions for a template name."""
        return [v for (n, v), _ in self._templates.items() if n == name]


def render_template(
    template: PromptTemplate,
    payload: dict[str, Any],
) -> tuple[list[dict[str, str]], int]:
    """Render a prompt template with evidence payload.

    Args:
        template: PromptTemplate to render
        payload: Evidence data to insert

    Returns:
        Tuple of (messages list, estimated token count)
    """
    user_content = template.user_template.format(**payload)

    messages = [
        {"role": "system", "content": template.system_prompt},
        {"role": "user", "content": user_content},
    ]

    estimated_tokens = _estimate_tokens(template.system_prompt) + _estimate_tokens(user_content)

    return messages, estimated_tokens


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (~4 chars per token)."""
    return max(1, len(text) // 4)
