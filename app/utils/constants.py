"""Shared domain constants."""

from __future__ import annotations

VALID_SEVERITIES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
SEVERITY_RANK: dict[str, int] = {level: index for index, level in enumerate(VALID_SEVERITIES, 1)}

RISK_MERCHANT_CATEGORIES: dict[str, list[str]] = {
    "high": [
        "7999",
        "4812",
        "5812",
        "5814",
        "5921",
        "5947",
        "6012",
        "6051",
        "6211",
        "7299",
        "7832",
    ],
    "medium": ["5411", "5541", "5732", "5734", "5942", "5999", "7512", "7513", "7538", "7542"],
}
