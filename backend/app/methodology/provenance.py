"""Human-in-the-loop provenance for official scoring inputs.

AI_SUGGESTED values may never become official scoring inputs silently.
"""

from __future__ import annotations

OFFICIAL_SOURCES = {
    "HUMAN_ENTERED",
    "HUMAN_CONFIRMED",
    "HUMAN_EDITED",
}

AI_SOURCE = "AI_SUGGESTED"
APPROVED = "APPROVED"


class ProvenanceError(ValueError):
    def __init__(self, message: str, *, rejected: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.rejected = rejected or []


def _unwrap(value):
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), str(value.get("source") or "").upper() or None
    return value, None


def filter_official_scores(scores: dict | None, provenance: dict | None = None) -> tuple[dict, list[str]]:
    """Return numeric scores that are eligible for the deterministic engine.

    Supports either:
    - plain numeric trees (all treated as HUMAN_ENTERED when provenance omitted), or
    - trees of {value, source} objects, or
    - a parallel provenance map with the same paths.
    """
    scores = scores or {}
    provenance = provenance or {}
    rejected: list[str] = []

    def resolve(path: str, node, prov_node):
        if isinstance(node, dict) and "value" not in node:
            out = {}
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else key
                child_prov = None
                if isinstance(prov_node, dict):
                    child_prov = prov_node.get(key)
                resolved = resolve(child_path, child, child_prov)
                if resolved is not None:
                    out[key] = resolved
            return out

        value, inline_source = _unwrap(node)
        source = inline_source
        if source is None and isinstance(prov_node, str):
            source = prov_node.upper()
        elif source is None and isinstance(prov_node, dict):
            source = str(prov_node.get("source") or "").upper() or None

        # Plain numeric payloads without provenance are accepted as human-entered
        # for calculator/demo use. Official submission scoring should send provenance.
        if source is None:
            source = "HUMAN_ENTERED"
        if source == AI_SOURCE or source not in OFFICIAL_SOURCES:
            rejected.append(path or "score")
            return None
        return value

    cleaned = resolve("", scores, provenance) or {}
    return cleaned, rejected


def require_human_approval(human_review: dict | None) -> None:
    status = str((human_review or {}).get("status") or "").upper()
    if status != APPROVED:
        raise ProvenanceError(
            "Official scoring requires humanReview.status = APPROVED. "
            "AI-suggested values alone are not enough."
        )
