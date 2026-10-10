"""Consistent repository identity normalization for discovery and saved state."""

import re


def normalize_github_name(value):
    """Accept an owner/repository alias and return its canonical queue name."""
    if not isinstance(value, str):
        raise ValueError("GitHub identity must be an owner/repository string")
    name = value.strip().strip("/").lower().removesuffix(".git")
    if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", name):
        raise ValueError(
            "GitHub identity requires nonempty owner/repository components"
        )
    return name
