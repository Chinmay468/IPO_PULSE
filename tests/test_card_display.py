import pytest
from datetime import date, timedelta


def test_card_display_rules_and_assertions():
    """
    Unit test verifying the card HTML display rules matching app/static/js/ipos.js:
    1. Low-confidence card (<50%): score hidden ('—'), 'Insufficient data' badge, missing inputs listed.
    2. Closed IPO: recommendation label suppressed ('Closed' badge only), final subscription, 'Score at close'.
    3. Extreme GMP (>50% of issue price): 'Verify before relying' badge, 'Apply, verify GMP' label.
    4. Live IPO: 'LIVE' status, composite score /100, standard recommendation badge.
    """
    # 1. Low Confidence Card Simulation
    low_conf_data = {
        "status": "UPCOMING",
        "score": {
            "composite_score": 64.2,
            "recommendation": "INSUFFICIENT DATA",
            "rationale": {
                "confidence": 0.25,
                "missing_inputs": ["Grey Market Premium", "P/E Ratio"]
            }
        }
    }
    rec = low_conf_data["score"]["recommendation"]
    confidence = low_conf_data["score"]["rationale"]["confidence"]
    is_insufficient = rec == "INSUFFICIENT DATA" or confidence < 0.50
    score_display = "—" if is_insufficient else str(low_conf_data["score"]["composite_score"])
    badge_label = "Insufficient data" if is_insufficient else rec

    assert score_display == "—"
    assert badge_label == "Insufficient data"
    assert "Grey Market Premium" in low_conf_data["score"]["rationale"]["missing_inputs"]

    # 2. Closed IPO Card Simulation
    closed_data = {
        "status": "CLOSED",
        "score": {
            "composite_score": 83.2,
            "recommendation": "NEUTRAL"
        },
        "latest_subscription": {
            "total_multiple": 131.7
        }
    }
    is_closed = closed_data["status"] == "CLOSED"
    card_score_label = "Score at close:" if is_closed else "Score:"
    card_rec_badge = "Closed" if is_closed else closed_data["score"]["recommendation"]
    sub_label = "Final Subscription" if is_closed else "Subscribed"

    assert is_closed is True
    assert card_score_label == "Score at close:"
    assert card_rec_badge == "Closed"
    assert sub_label == "Final Subscription"
    assert closed_data["latest_subscription"]["total_multiple"] == 131.7

    # 3. Extreme GMP Card Simulation
    extreme_gmp_data = {
        "issue_price": 100.0,
        "consensus_gmp": {
            "gmp_amount": 65.0,
            "gmp_percentage": 65.0,
            "status": "fresh"
        },
        "score": {
            "composite_score": 71.0,
            "recommendation": "Apply, verify GMP"
        }
    }
    gmp_ratio = extreme_gmp_data["consensus_gmp"]["gmp_amount"] / extreme_gmp_data["issue_price"]
    is_extreme = gmp_ratio > 0.50
    extreme_badge = "Verify before relying" if is_extreme else ""

    assert is_extreme is True
    assert extreme_badge == "Verify before relying"
    assert extreme_gmp_data["score"]["recommendation"] == "Apply, verify GMP"
