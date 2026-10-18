"""
Canonical Scoring Configuration for IPO Pulse.
This module defines the single source of truth for:
- Pillar weights (35/30/20/15)
- Recommendation score cutoffs
- GMP thresholds (Mainboard vs SME)
- Subscription thresholds and linear interpolation rules (QIB, Retail, Total)
- Valuation multiples (P/E discount vs industry, absolute P/E fallback, RoNW)
- Issue structure parameters (Fresh ratio %, Mainboard & SME issue size sweet spots)
- Versioning, notes, and unmodeled risk factors.
"""

from typing import Dict, Any

SCORING_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "updated_at": "2026-10-05",
    "changelog": "v1.0 (2026-10-05): Added ₹100–300 Cr Mainboard size tier, linear QIB interpolation, restored absolute P/E fallback, and integrated dynamic config endpoint.",
    "weights": {
        "gmp": {
            "key": "gmp",
            "name": "Grey Market Premium (GMP)",
            "max_points": 35.0,
            "weight_pct": 35.0,
            "color": "emerald",
            "description": "Measures unlisted OTC demand, listing cushion, and buyer sentiment."
        },
        "subscription": {
            "key": "subscription",
            "name": "Subscription Demand",
            "max_points": 30.0,
            "weight_pct": 30.0,
            "color": "blue",
            "description": "Evaluates institutional (QIB), retail, and aggregate bidding demand."
        },
        "valuation": {
            "key": "valuation",
            "name": "Valuation & Financials",
            "max_points": 20.0,
            "weight_pct": 20.0,
            "color": "purple",
            "description": "Compares P/E multiple against sector peers and assesses capital efficiency (RoNW)."
        },
        "structure": {
            "key": "structure",
            "name": "Structure & Fresh Issue",
            "max_points": 15.0,
            "weight_pct": 15.0,
            "color": "amber",
            "description": "Reviews primary fresh growth capital vs secondary OFS exit and issue liquidity sizing."
        }
    },
    "recommendation_cutoffs": [
        {
            "tier": "STRONG APPLY",
            "min_score": 75.0,
            "max_score": 100.0,
            "badge_class": "badge-STRONG_APPLY",
            "color": "emerald",
            "description": "High conviction opportunity backed by robust grey market premium, heavy subscription interest, or solid financial fundamentals."
        },
        {
            "tier": "APPLY",
            "min_score": 60.0,
            "max_score": 74.99,
            "badge_class": "badge-APPLY",
            "color": "blue",
            "description": "Favourable risk-reward ratio with healthy demand indicators and reasonable valuation."
        },
        {
            "tier": "NEUTRAL",
            "min_score": 45.0,
            "max_score": 59.99,
            "badge_class": "badge-NEUTRAL",
            "color": "amber",
            "description": "Mixed signals; consider applying only if retail subscription or GMP accelerates closer to closing date."
        },
        {
            "tier": "AVOID",
            "min_score": 0.0,
            "max_score": 44.99,
            "badge_class": "badge-AVOID",
            "color": "rose",
            "description": "Unfavourable risk-reward ratio due to muted demand, negative/negligible GMP, or elevated valuation."
        },
        {
            "tier": "INSUFFICIENT DATA",
            "min_score": 0.0,
            "max_score": 100.0,
            "badge_class": "badge-INSUFFICIENT_DATA",
            "color": "slate",
            "description": "Evaluated inputs account for less than 50% available confidence weight. Score is not finalized to prevent false avoid signals."
        }
    ],
    "missing_data_policy": {
        "rule": "Proportional Scaling",
        "description": "Missing inputs contribute 0 points AND are excluded from the maximum available weight denominator, so the score is scaled to the points that could be evaluated. Never awards default points for unknown data.",
        "confidence_threshold": 0.50,
        "confidence_formula": "Confidence = Available Evaluated Weight / 100. If confidence < 50%, recommendation is INSUFFICIENT DATA (neutral grey)."
    },
    "pillars": {
        "gmp": {
            "title": "1. Grey Market Premium (GMP)",
            "max_points": 35.0,
            "interpolated": True,
            "interpolation_note": "Values between threshold cutoffs (0%–5%, 5%–10%/15%, 10%/15%–20%/30%, 20%/30%–35%/50%) are linearly interpolated.",
            "mainboard": [
                {"condition": "≥ 35.0% GMP", "tier": "Bumper Listing Potential", "points": "35.0", "min_pct": 35.0, "max_pts": 35.0},
                {"condition": "20.0% – 34.9% GMP", "tier": "Strong Demand", "points": "28.0 – 35.0", "min_pct": 20.0, "max_pts": 35.0},
                {"condition": "10.0% – 19.9% GMP", "tier": "Healthy Cushion", "points": "18.0 – 28.0", "min_pct": 10.0, "max_pts": 28.0},
                {"condition": "5.0% – 9.9% GMP", "tier": "Modest Premium", "points": "10.0 – 18.0", "min_pct": 5.0, "max_pts": 18.0},
                {"condition": "0.0% – 4.9% GMP", "tier": "Subdued Demand", "points": "4.0 – 10.0", "min_pct": 0.0, "max_pts": 10.0},
                {"condition": "< 0.0% GMP", "tier": "Discount / Listing Loss Risk", "points": "0.0", "min_pct": None, "max_pts": 0.0}
            ],
            "sme": [
                {"condition": "≥ 50.0% GMP", "tier": "Bumper Listing Potential (SME)", "points": "35.0", "min_pct": 50.0, "max_pts": 35.0},
                {"condition": "30.0% – 49.9% GMP", "tier": "Strong Demand (SME)", "points": "28.0 – 35.0", "min_pct": 30.0, "max_pts": 35.0},
                {"condition": "15.0% – 29.9% GMP", "tier": "Healthy Cushion (SME)", "points": "18.0 – 28.0", "min_pct": 15.0, "max_pts": 28.0},
                {"condition": "5.0% – 14.9% GMP", "tier": "Modest Premium", "points": "10.0 – 18.0", "min_pct": 5.0, "max_pts": 18.0},
                {"condition": "0.0% – 4.9% GMP", "tier": "Subdued Demand", "points": "4.0 – 10.0", "min_pct": 0.0, "max_pts": 10.0},
                {"condition": "< 0.0% GMP", "tier": "Discount / Listing Loss Risk", "points": "0.0", "min_pct": None, "max_pts": 0.0}
            ],
            "special_adjustments": [
                {"condition": "No GMP recorded yet", "points": "15.0", "note": "Neutral baseline applied before grey market opens."},
                {"condition": "Kostak / Subject-to-Sauda active", "points": "+1.5", "note": "Added bonus for confirmed application demand (capped at 35.0 pts)."}
            ]
        },
        "subscription": {
            "title": "2. Subscription Demand",
            "max_points": 30.0,
            "interpolated": True,
            "interpolation_note": "QIB points are linearly interpolated between 0x–1x, 1x–5x, and 5x–Target (30x Mainboard / 60x SME) to eliminate step discontinuities.",
            "components": [
                {
                    "name": "QIB Institutional Demand",
                    "max_points": 16.0,
                    "target_mainboard": 30.0,
                    "target_sme": 60.0,
                    "rules": [
                        {"condition": "≥ 30x Mainboard / ≥ 60x SME (Target)", "points": "16.0", "note": "Massive institutional validation."},
                        {"condition": "5x to Target (30x/60x)", "points": "10.0 – 16.0", "note": "Linearly interpolated: 10.0 + ((qib - 5.0) / (target - 5.0)) * 6.0."},
                        {"condition": "1x to 5x", "points": "6.0 – 10.0", "note": "Linearly interpolated: 6.0 + ((qib - 1.0) / 4.0) * 4.0."},
                        {"condition": "< 1x (Day 3 / Final Closing)", "points": "1.0 – 6.0", "note": "Linearly interpolated: 1.0 + (qib * 5.0) based on undersubscription."},
                        {"condition": "< 1x (Day 1 / Day 2 Early Bidding)", "points": "5.0", "note": "Not penalized early; QIB bids typically concentrate on Day 3."},
                        {"condition": "No QIB data recorded", "points": "5.0 (early) / 3.0 (late)", "note": "Neutral fallback."}
                    ]
                },
                {
                    "name": "Retail Public Demand",
                    "max_points": 6.0,
                    "target_mainboard": 10.0,
                    "target_sme": 25.0,
                    "rules": [
                        {"condition": "≥ 10x Mainboard / ≥ 25x SME", "points": "6.0", "note": "Exceptional retail enthusiasm."},
                        {"condition": "≥ 30% of Target (3x Main / 7.5x SME)", "points": "4.5", "note": "Solid retail interest."},
                        {"condition": "≥ 1.0x", "points": "3.0", "note": "Fully subscribed retail category."},
                        {"condition": "< 1.0x", "points": "1.0", "note": "Undersubscribed retail portion."},
                        {"condition": "No retail data recorded", "points": "2.0", "note": "Baseline neutral fallback."}
                    ]
                },
                {
                    "name": "Total Issue Oversubscription",
                    "max_points": 8.0,
                    "target_mainboard": 35.0,
                    "target_sme": 50.0,
                    "rules": [
                        {"condition": "≥ 35x Mainboard / ≥ 50x SME", "points": "8.0", "note": "Massive aggregate oversubscription."},
                        {"condition": "≥ 40% of Target (14x Main / 20x SME)", "points": "6.5", "note": "Healthy overall book."},
                        {"condition": "≥ 3.0x", "points": "5.0", "note": "Moderate issue oversubscription."},
                        {"condition": "≥ 1.0x", "points": "3.0", "note": "Fully covered book."},
                        {"condition": "< 1.0x", "points": "0.5", "note": "Issue undersubscribed overall."},
                        {"condition": "No total data recorded", "points": "2.0", "note": "Baseline neutral fallback."}
                    ]
                }
            ]
        },
        "valuation": {
            "title": "3. Valuation & Financials",
            "max_points": 20.0,
            "interpolated": False,
            "components": [
                {
                    "name": "P/E vs Industry Peers (Primary)",
                    "max_points": 12.0,
                    "rules": [
                        {"condition": "> 25% discount to industry P/E", "points": "12.0", "note": "Highly attractive pricing."},
                        {"condition": "5% – 25% discount to industry", "points": "10.0", "note": "Fairly valued with margin of safety."},
                        {"condition": "Fair to ≤ 15% premium vs industry", "points": "7.0", "note": "Neutral industry pricing."},
                        {"condition": "15% – 35% premium vs industry", "points": "4.0", "note": "Aggressive pricing."},
                        {"condition": "> 35% premium vs industry", "points": "1.5", "note": "Expensive valuation multiple."},
                        {"condition": "Negative P/E (Loss-making operations)", "points": "2.0", "note": "High risk tech / unproven profitability."}
                    ]
                },
                {
                    "name": "Absolute P/E Fallback (When Industry P/E Unavailable)",
                    "max_points": 12.0,
                    "rules": [
                        {"condition": "P/E < 25.0", "points": "9.0", "note": "Attractive absolute multiple."},
                        {"condition": "25.0 ≤ P/E < 45.0", "points": "6.5", "note": "Moderate absolute multiple."},
                        {"condition": "P/E ≥ 45.0", "points": "3.0", "note": "Elevated absolute multiple risk."}
                    ]
                },
                {
                    "name": "Return on Net Worth (RoNW) Capital Efficiency",
                    "max_points": 8.0,
                    "rules": [
                        {"condition": "≥ 20.0%", "points": "8.0", "note": "Robust capital efficiency."},
                        {"condition": "15.0% – 19.9%", "points": "6.5", "note": "Healthy return on equity."},
                        {"condition": "10.0% – 14.9%", "points": "4.5", "note": "Average capital efficiency."},
                        {"condition": "0.1% – 9.9%", "points": "2.5", "note": "Sub-par return on net worth."},
                        {"condition": "≤ 0.0% (Net losses)", "points": "0.0", "note": "Negative net worth / ongoing burn."},
                        {"condition": "Missing RoNW metric", "points": "4.0", "note": "Default neutral midpoint."}
                    ]
                }
            ]
        },
        "structure": {
            "title": "4. Structure & Fresh Issue",
            "max_points": 15.0,
            "interpolated": False,
            "components": [
                {
                    "name": "Fresh Issue Ratio",
                    "max_points": 10.0,
                    "rules": [
                        {"condition": "≥ 75% Fresh Issue proceeds", "points": "10.0", "note": "Primary capital allocated for business growth and capex."},
                        {"condition": "40% – 74.9% Fresh Issue", "points": "7.5", "note": "Balanced growth and promoter liquidity."},
                        {"condition": "15% – 39.9% Fresh Issue", "points": "5.0", "note": "Moderate Offer for Sale (OFS) component."},
                        {"condition": "< 15% Fresh Issue", "points": "2.0", "note": "Predominantly OFS; funds exit to selling promoters."},
                        {"condition": "Unknown / Missing breakdown", "points": "6.5", "note": "Default neutral ratio."}
                    ]
                },
                {
                    "name": "Issue Size & Market Liquidity Comfort",
                    "max_points": 5.0,
                    "mainboard_rules": [
                        {"condition": "₹300 Cr – ₹5,000 Cr", "tier": "Mainboard Sweet Spot", "points": "5.0", "note": "Optimal institutional and retail liquidity."},
                        {"condition": "₹100 Cr – ₹300 Cr", "tier": "Mid-Sized Issue", "points": "4.0", "note": "Adequate liquidity with minor float constraint."},
                        {"condition": "> ₹5,000 Cr", "tier": "Mega Issue", "points": "3.5", "note": "Significant supply overhang requiring heavy absorption."},
                        {"condition": "< ₹100 Cr", "tier": "Micro-Cap Mainboard", "points": "3.0", "note": "Elevated illiquidity and client concentration risk."}
                    ],
                    "sme_rules": [
                        {"condition": "₹15 Cr – ₹60 Cr", "tier": "SME Sweet Spot", "points": "5.0", "note": "Balanced size for SME platform trading."},
                        {"condition": "> ₹60 Cr", "tier": "Large SME", "points": "4.0", "note": "Higher subscription requirement for SME float."},
                        {"condition": "< ₹15 Cr", "tier": "Micro SME", "points": "3.0", "note": "Severe liquidity risk in secondary trading."}
                    ],
                    "default_rule": {"points": "3.5", "note": "Default liquidity points when size is unspecified."}
                }
            ]
        }
    },
    "notes": {
        "disclaimer": "Weights and scoring parameters are heuristic and not backtested; Grey Market Premium (GMP) is unofficial OTC sentiment and can be manipulated.",
        "not_yet_included": [
            {"factor": "GMP Trend", "description": "Rate of change and premium acceleration/deceleration over the 3–5 trading days leading to listing."},
            {"factor": "Anchor Investors", "description": "Institutional anchor book pedigree, sovereign fund participation, and 30-day/90-day lock-in expiry windows."},
            {"factor": "Post-Issue Promoter Holding", "description": "Skin-in-the-game dilution, pledge percentages, and non-compete covenants."},
            {"factor": "Minimum Investment Ticket Size", "description": "Application capital requirements and lot-size liquidity barriers (especially ₹1 Lakh+ in SME)."}
        ]
    }
}
