"""Cross-request similarity check.

Port of the prototype's token comparison. The portal kept this in the
browser; the API applies it across every stored submission.
"""

from __future__ import annotations

import re

from app.methodology.engine import js_math_round

DUPLICATE_THRESHOLD = 80


def normalize_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def token_similarity(left, right) -> float:
    a = {token for token in normalize_text(left).split() if len(token) > 2}
    b = {token for token in normalize_text(right).split() if len(token) > 2}
    if not a or not b:
        return 0.0
    overlap = sum(1 for token in a if token in b)
    return (2 * overlap) / (len(a) + len(b))


def compare_submissions(current: dict, prior: dict) -> int:
    old = prior or {}
    weighted = [
        (0.40, token_similarity(current.get("description") or current.get("summary"), old.get("description") or old.get("summary"))),
        (0.20, token_similarity(current.get("summary"), old.get("summary"))),
        (0.15, token_similarity(current.get("name"), old.get("name"))),
        (0.15, token_similarity(current.get("requirements"), old.get("requirements"))),
        (0.07, 1.0 if current.get("category") and current.get("category") == old.get("category") else 0.0),
        (0.03, token_similarity(current.get("screening"), old.get("screening"))),
    ]
    return js_math_round(sum(weight * score for weight, score in weighted) * 100)


def closest_match(current: dict, priors: list[dict]) -> dict | None:
    best = None
    best_score = -1
    for prior in priors:
        score = compare_submissions(current, prior.get("comparable") or {})
        if score > best_score:
            best_score = score
            best = prior
    if best is None:
        return None
    return {**best, "similarity": best_score}
