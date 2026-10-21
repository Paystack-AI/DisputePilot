"""Loads prompt text from this folder."""

from pathlib import Path

PROMPTS_DIR: Path = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    """Returns the contents of prompts/<name> (the .txt suffix is optional)."""
    filename: str = name if name.endswith(".txt") else f"{name}.txt"
    path: Path = (PROMPTS_DIR / filename).resolve()
    if path.parent != PROMPTS_DIR:
        raise ValueError(f"prompt must live in {PROMPTS_DIR.name}/: {name}")
    return path.read_text(encoding="utf-8").strip()
