
"""Read approved Syra explanations from the assessment CSV.
This is a fixed CSV lookup. No LLM or RAG.
"""

import csv
from functools import lru_cache
from pathlib import Path


# Maps the frontend Risk Profile question IDs to CSV question numbers.
QUESTION_IDS = {
    "rp_host": 1,
    "rp_vendor": 2,
    "rp_data": 3,
    "rp_scale": 4,
    "rp_share": 5,
    "rp_profile": 6,
    "rp_role": 7,
    "rp_stakes": 8,
    "rp_who": 9,
    "rp_vulnerable": 10,
    "rp_explain": 11,
    "rp_reg": 12,
    "rp_act": 13,
    "rp_trigger": 14,
    "rp_freq": 15,
    "rp_fallback": 16,
    "rp_model": 17,
    "rp_human": 18,
    "rp_guard": 19,
    "rp_owner": 20,
}


CSV_PATH = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "SYRA_Assessment_Questions_and_Logic(Questions).csv"
)


@lru_cache(maxsize=1)
def _load_explanations() -> dict[int, str]:
    if not CSV_PATH.is_file():
        raise FileNotFoundError(
            f"Syra explanations CSV not found: {CSV_PATH}"
        )

    with CSV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        rows = csv.reader(file)

        number_col = None
        explanation_col = None

        # Find the actual header row; the CSV has introductory rows first.
        for row in rows:
            normalized = [cell.strip() for cell in row]

            if (
                "#" in normalized
                and "Syra explains (“?”)" in normalized
            ):
                number_col = normalized.index("#")
                explanation_col = normalized.index(
                    "Syra explains (“?”)"
                )
                break

        if number_col is None or explanation_col is None:
            raise ValueError(
                "Could not find the required columns in the Syra CSV."
            )

        explanations = {}
        
        for row in rows:
            normalized = [cell.strip() for cell in row]

            # Stop reading when Part B begins.
            if any(
                cell.startswith("PART B:")
                for cell in normalized
            ):
                break

            if len(row) <= max(number_col, explanation_col):
                continue

            raw_number = row[number_col].strip()
            explanation = row[explanation_col].strip()

            if raw_number.isdigit() and explanation:
                explanations[int(raw_number)] = explanation

    return explanations


def get_explanation(question_id: str) -> str | None:
    question_number = QUESTION_IDS.get(question_id)

    if question_number is None:
        return None

    return _load_explanations().get(question_number)
