#!/usr/bin/env python3
"""Regression for deterministic design line breaks and per-run font weights."""

from __future__ import annotations

from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from generate_canvas import display_text_contract, dynamic_slot_expression, run_font_weight  # noqa: E402


def main() -> int:
    feedback = {
        "text": "How was your experience? Let us know!",
        "bbox": [178, 801, 493, 66],
        "fontSize": 28,
        "weight": 400,
        "textRuns": [{"content": "How was your experience? Let us know!"}],
    }
    feedback_text, _ = display_text_contract(feedback)
    if feedback_text != "How was your experience? Let us\nknow!":
        raise AssertionError(feedback_text)
    feedback_expression = dynamic_slot_expression("feedback", feedback, feedback_text)
    if "slotText['feedback'] == 'How was your experience? Let us know!'" not in feedback_expression:
        raise AssertionError(feedback_expression)

    waiting = {
        "text": "Your order is undergoing pre-disbursement risk checks. Please wait for the result.",
        "bbox": [121, 512, 508, 93], "fontSize": 26, "lineHeight": None, "textRuns": [],
    }
    waiting_text, _ = display_text_contract(waiting)
    if waiting_text != "Your order is undergoing pre-\ndisbursement risk checks. Please wait for\nthe result.":
        raise AssertionError(waiting_text)

    support = {
        "text": "Need help? Chat with our support team online.",
        "bbox": [178, 946, 493, 66], "fontSize": 28, "lineHeight": None, "textRuns": [],
    }
    support_text, _ = display_text_contract(support)
    if support_text != "Need help? Chat with our support\nteam online.":
        raise AssertionError(support_text)

    rejected = {
        "text": "Not approved. Please try again in 14 days after updating your information.",
        "bbox": [122, 515, 506, 62], "fontSize": 26, "lineHeight": None,
        "textRuns": [
            {"content": "Not approved. Please try again in ", "color": "#222222"},
            {"content": "14 days", "color": "#FF0000"},
            {"content": " after updating your information.", "color": "#222222"},
        ],
    }
    rejected_text, rejected_runs = display_text_contract(rejected)
    if rejected_text != "Not approved. Please try again in 14 days\nafter updating your information.":
        raise AssertionError(rejected_text)
    if [run["content"] for run in rejected_runs] != [
        "Not approved. Please try again in ", "14 days\n", "after updating your information.",
    ]:
        raise AssertionError(rejected_runs)

    interest = {
        "text": "Daily Interest Rate: < 0.05%",
        "bbox": [415, 481.5, 237, 61],
        "fontSize": 24,
        "weight": 400,
        "textRuns": [
            {"content": "Daily Interest Rate: ", "font": {"fontWeight": 400}},
            {"content": "< 0.05%", "font": {"fontWeight": 500}},
        ],
    }
    interest_text, interest_runs = display_text_contract(interest)
    if interest_text != "Daily Interest Rate:\n< 0.05%":
        raise AssertionError(interest_text)
    if [run["content"] for run in interest_runs] != ["Daily Interest Rate:\n", "< 0.05%"]:
        raise AssertionError(interest_runs)
    if run_font_weight(interest_runs[1], interest) != "FontWeight.w500":
        raise AssertionError(run_font_weight(interest_runs[1], interest))

    amount = {
        "text": "₦50,000", "bbox": [80, 410, 300, 58],
        "fontSize": 56, "weight": 700,
        "textRuns": [
            {"content": "₦", "font": {"fontWeight": 400}},
            {"content": "50,000", "font": {"fontWeight": 700}},
        ],
    }
    amount_text, amount_runs = display_text_contract(amount)
    if "\n" in amount_text or any("\n" in str(run.get("content")) for run in amount_runs):
        raise AssertionError((amount_text, amount_runs))

    print("ok generate canvas text layout selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
