"""Unified-diff extraction from a model response (strips prose/fences)."""
import re


def extract_diff(text: str) -> str:
    m = re.search(r"```(?:diff|patch)?\s*(.*?)```", text or "", re.S)
    return m.group(1) if m else (text or "")
