from datetime import date, datetime, timezone
from typing import Optional, Dict, Any, List
from app.models.ipo import IPO, IPOSubscription, IPOGmp, IPOType, IPOStatus, RecommendationType
from app.core.scoring_config import SCORING_CONFIG
from app.core.ipo_timeline import derive_ipo_status


class ScoringService:
    @staticmethod
    def calculate_score(
        ipo: IPO,
        latest_subscription: Optional[IPOSubscription] = None,
        latest_gmp: Optional[IPOGmp] = None
    ) -> Dict[str, Any]:
        """
        Computes an institutional-grade multi-parameter composite score (0-100) and recommendation.
        Missing data logic:
        - Tracks which inputs are present (GMP, subscription, P/E, RoNW, fresh issue %, issue size).
        - A missing input contributes NO points AND is excluded from the maximum, so the score is
          scaled to the points that could be evaluated (e.g. 28 of 50 = 56/100).
        - Confidence value = available_weight / 100. Never awards default points for unknown data.
        - If confidence < 50%, recommendation is INSUFFICIENT DATA (neutral grey), not AVOID.
        - Closed/Listed IPOs show final subscription/listing details and do not recommend applying.
        """
        positive_factors: List[str] = []
        risk_factors: List[str] = []

        is_sme = (ipo.ipo_type == IPOType.SME)
        today = date.today()

        inputs_present: Dict[str, bool] = {
            "gmp": False,
            "subscription": False,
            "pe": False,
            "ronw": False,
            "fresh_issue": False,
            "issue_size": False
        }
        missing_inputs: List[str] = []

        # ---------------- 1. GMP Component (Max 35) ----------------
        max_gmp_pts = 35.0
        gmp_score = 0.0
        gmp_pct: Optional[float] = None

        # Check freshness: older than 24 hours counts as missing
        gmp_fresh = False
        if latest_gmp:
            if latest_gmp.recorded_at:
                gmp_dt = latest_gmp.recorded_at if latest_gmp.recorded_at.tzinfo else latest_gmp.recorded_at.replace(tzinfo=timezone.utc)
                age_secs = (datetime.now(timezone.utc) - gmp_dt).total_seconds()
                if age_secs <= 86400:  # 24 hours
                    gmp_fresh = True
            else:
                gmp_fresh = True

        if latest_gmp and gmp_fresh:
            gmp_pct = latest_gmp.gmp_percentage
            if (gmp_pct is None or gmp_pct == 0) and (latest_gmp.gmp_amount is not None and latest_gmp.gmp_amount > 0):
                base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low
                if base_price and base_price > 0:
                    gmp_pct = (latest_gmp.gmp_amount / base_price) * 100.0

        is_extreme_gmp = False
        if gmp_pct is not None:
            inputs_present["gmp"] = True
            bumper_cutoff = 50.0 if is_sme else 35.0
            strong_cutoff = 30.0 if is_sme else 20.0
            healthy_cutoff = 15.0 if is_sme else 10.0

            # Extreme GMP condition: consensus GMP > 50% of issue price
            base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low
            if base_price and base_price > 0 and latest_gmp and latest_gmp.gmp_amount is not None:
                if (latest_gmp.gmp_amount / base_price) > 0.50 or gmp_pct > 50.0:
                    is_extreme_gmp = True

            if gmp_pct >= bumper_cutoff:
                gmp_score = 35.0
                positive_factors.append(f"Exceptional Grey Market Premium of {gmp_pct:.1f}% indicates bumper listing potential.")
            elif gmp_pct >= strong_cutoff:
                gmp_score = 28.0 + ((gmp_pct - strong_cutoff) / (bumper_cutoff - strong_cutoff)) * 7.0
                positive_factors.append(f"Strong Grey Market Premium of {gmp_pct:.1f}% indicates high listing day demand.")
            elif gmp_pct >= healthy_cutoff:
                gmp_score = 18.0 + ((gmp_pct - healthy_cutoff) / (strong_cutoff - healthy_cutoff)) * 10.0
                positive_factors.append(f"Healthy Grey Market Premium of {gmp_pct:.1f}% offers reasonable safety cushion.")
            elif gmp_pct >= 5.0:
                gmp_score = 10.0 + ((gmp_pct - 5.0) / max(1.0, (healthy_cutoff - 5.0))) * 8.0
                risk_factors.append(f"Modest Grey Market Premium of {gmp_pct:.1f}%; vulnerable to market volatility.")
            elif gmp_pct >= 0.0:
                gmp_score = 4.0 + (gmp_pct / 5.0) * 6.0
                risk_factors.append(f"Subdued Grey Market Premium of {gmp_pct:.1f}%; low margin of safety.")
            else:
                gmp_score = 0.0
                risk_factors.append(f"Negative Grey Market Premium ({gmp_pct:.1f}%); discount indicates listing loss risk.")

            if latest_gmp.subject_to_sauda and latest_gmp.subject_to_sauda > 0:
                positive_factors.append(f"Active Subject-to-Sauda premium (₹{latest_gmp.subject_to_sauda:.0f}) confirms firm retail buyer interest.")
                gmp_score = min(max_gmp_pts, gmp_score + 1.5)

            # Cap GMP score points at 'strong' band (max 28.0) when extreme GMP is flagged
            if is_extreme_gmp:
                gmp_score = min(28.0, gmp_score)
                risk_factors.append(f"Extreme GMP ({gmp_pct:.1f}% of issue price exceeds 50%); capped at strong tier. Verify before relying.")
        else:
            gmp_score = 0.0
            missing_inputs.append("Grey Market Premium (GMP)")

        gmp_score = min(max_gmp_pts, max(0.0, gmp_score))

        # ---------------- 2. Subscription Component (Max 30) ----------------
        max_sub_pts = 30.0
        subscription_score = 0.0

        if latest_subscription and (
            latest_subscription.total_multiple is not None or
            latest_subscription.qib_multiple is not None or
            latest_subscription.retail_multiple is not None
        ):
            inputs_present["subscription"] = True
            qib = latest_subscription.qib_multiple
            retail = latest_subscription.retail_multiple
            total = latest_subscription.total_multiple if latest_subscription.total_multiple is not None else 0.0

            derived_status = derive_ipo_status(ipo.open_date, ipo.close_date, ipo.listing_date)
            is_closed_or_listed = (derived_status in (IPOStatus.CLOSED, IPOStatus.LISTED)) or (ipo.close_date and today > ipo.close_date)

            is_early_bidding = False
            if not is_closed_or_listed:
                if latest_subscription.day_number and latest_subscription.day_number < 3:
                    is_early_bidding = True
                elif ipo.open_date and today <= (ipo.open_date if hasattr(ipo.open_date, '__add__') else today):
                    is_early_bidding = True

            total_target = 50.0 if is_sme else 35.0
            qib_target = 60.0 if is_sme else 30.0
            retail_target = 25.0 if is_sme else 10.0

            # Special case: If only total_multiple is known (e.g. from general scraper like InvestorGain 131.7x,
            # or breakdowns are unpopulated/zero while overall total > 1.0),
            # scale subscription score directly from total multiple rather than penalizing for missing breakdowns.
            if (qib is None and retail is None) or ((qib is None or qib == 0.0) and (retail is None or retail == 0.0) and total > 1.0):
                if total >= total_target:
                    subscription_score = 30.0
                    prefix = "Final subscription: " if is_closed_or_listed else ""
                    positive_factors.append(f"{prefix}Huge overall oversubscription of {total:.1f}x across categories.")
                elif total >= (total_target * 0.4):
                    subscription_score = 22.0
                    prefix = "Final subscription: " if is_closed_or_listed else ""
                    positive_factors.append(f"{prefix}Strong overall subscription of {total:.1f}x.")
                elif total >= 3.0:
                    subscription_score = 16.0
                    positive_factors.append(f"Healthy overall subscription of {total:.1f}x.")
                elif total >= 1.0:
                    subscription_score = 10.0
                else:
                    subscription_score = max(0.0, total * 8.0)
                    if not is_early_bidding:
                        risk_factors.append(f"Overall issue undersubscribed ({total:.2f}x).")
            else:
                # Broken-down components
                qib_pts = 0.0
                if qib is not None:
                    if qib >= qib_target:
                        qib_pts = 16.0
                        positive_factors.append(f"Massive institutional interest with QIB subscribed {qib:.1f}x.")
                    elif qib >= 5.0:
                        qib_pts = 10.0 + ((qib - 5.0) / (qib_target - 5.0)) * 6.0
                        positive_factors.append(f"Strong QIB subscription of {qib:.1f}x demonstrates institutional backing.")
                    elif qib >= 1.0:
                        qib_pts = 6.0 + ((qib - 1.0) / 4.0) * 4.0
                        positive_factors.append(f"Moderate QIB subscription of {qib:.1f}x.")
                    else:
                        if is_early_bidding:
                            qib_pts = 5.0
                            positive_factors.append("Bidding in progress; institutional QIB surge expected on closing day.")
                        else:
                            qib_pts = 1.0 + max(0.0, qib) * 5.0
                            risk_factors.append(f"Subdued QIB institutional demand ({qib:.2f}x).")

                retail_pts = 2.0
                if retail is not None:
                    if retail >= retail_target:
                        retail_pts = 6.0
                        positive_factors.append(f"Extremely high retail subscription ({retail:.1f}x).")
                    elif retail >= (retail_target * 0.3):
                        retail_pts = 4.5
                        positive_factors.append(f"Strong retail subscription of {retail:.1f}x.")
                    elif retail >= 1.0:
                        retail_pts = 3.0
                    else:
                        retail_pts = 1.0
                        if not is_early_bidding:
                            risk_factors.append(f"Retail category undersubscribed ({retail:.2f}x).")

                total_pts = 0.0
                if total is not None:
                    if total >= total_target:
                        total_pts = 8.0
                        prefix = "Final subscription: " if is_closed_or_listed else ""
                        positive_factors.append(f"{prefix}Huge overall oversubscription of {total:.1f}x.")
                    elif total >= (total_target * 0.4):
                        total_pts = 6.5
                        prefix = "Final subscription: " if is_closed_or_listed else ""
                        positive_factors.append(f"{prefix}Healthy total subscription of {total:.1f}x.")
                    elif total >= 3.0:
                        total_pts = 5.0
                    elif total >= 1.0:
                        total_pts = 3.0
                    else:
                        total_pts = 0.5
                        if not is_early_bidding:
                            prefix = "Final subscription: " if is_closed_or_listed else ""
                            risk_factors.append(f"{prefix}Total issue undersubscribed ({total:.2f}x).")

                subscription_score = min(max_sub_pts, qib_pts + retail_pts + total_pts)
        else:
            subscription_score = 0.0
            missing_inputs.append("Subscription Bidding Data")

        subscription_score = min(max_sub_pts, max(0.0, subscription_score))

        # ---------------- 3. Valuation & Financials (Max 20) ----------------
        # Split: P/E (Max 12) + RoNW (Max 8)
        pe = ipo.pe_ratio
        ind_pe = ipo.industry_pe
        ronw = ipo.ronw

        eps = getattr(ipo, "eps", None)
        pat_margin = getattr(ipo, "pat_margin_pct", None)
        is_loss_making = (
            (eps is not None and eps < 0)
            or (pat_margin is not None and pat_margin < 0)
            or (pe is not None and pe <= 0)
        )

        pe_pts = 0.0
        if is_loss_making:
            # When EPS or PAT is negative, P/E is not meaningful and excluded from P/E scoring
            inputs_present["pe"] = False
            risk_factors.append("Loss-making operations (P/E is not meaningful).")
        elif pe is not None and pe > 0:
            inputs_present["pe"] = True
            if ind_pe is not None and ind_pe > 0:
                pe_ratio_diff = (pe - ind_pe) / ind_pe
                if pe_ratio_diff <= -0.25:
                    pe_pts = 12.0
                    positive_factors.append(f"Attractive valuation: P/E of {pe:.1f} is at >25% discount to industry P/E ({ind_pe:.1f}).")
                elif pe_ratio_diff <= -0.05:
                    pe_pts = 10.0
                    positive_factors.append(f"Fairly valued: P/E of {pe:.1f} compares favourably against industry ({ind_pe:.1f}).")
                elif pe_ratio_diff <= 0.15:
                    pe_pts = 7.0
                elif pe_ratio_diff <= 0.35:
                    pe_pts = 4.0
                    risk_factors.append(f"Aggressive pricing: P/E of {pe:.1f} trades at premium to industry ({ind_pe:.1f}).")
                else:
                    pe_pts = 1.5
                    risk_factors.append(f"Expensive valuation: P/E of {pe:.1f} vs industry average of {ind_pe:.1f}.")
            else:
                if pe < 25.0:
                    pe_pts = 9.0
                    positive_factors.append(f"Reasonable absolute valuation: P/E of {pe:.1f} is under 25.")
                elif pe < 45.0:
                    pe_pts = 6.5
                else:
                    pe_pts = 3.0
                    risk_factors.append(f"High absolute P/E multiple ({pe:.1f}).")
        else:
            pe_pts = 0.0
            missing_inputs.append("P/E Ratio")
            risk_factors.append("P/E ratio missing; valuation cannot be assessed.")

        ronw_pts = 0.0
        if ronw is not None:
            inputs_present["ronw"] = True
            if ronw >= 20.0:
                ronw_pts = 8.0
                positive_factors.append(f"Robust Return on Net Worth (RoNW) of {ronw:.1f}%.")
            elif ronw >= 15.0:
                ronw_pts = 6.5
                positive_factors.append(f"Healthy Return on Net Worth of {ronw:.1f}%.")
            elif ronw >= 10.0:
                ronw_pts = 4.5
            elif ronw > 0:
                ronw_pts = 2.5
                risk_factors.append(f"Sub-par capital efficiency; RoNW is only {ronw:.1f}%.")
            else:
                ronw_pts = 0.0
                risk_factors.append("Negative Return on Net Worth reflects net losses.")
        else:
            ronw_pts = 0.0
            missing_inputs.append("Return on Net Worth (RoNW)")

        valuation_score = min(20.0, pe_pts + ronw_pts)

        # ---------------- 4. Issue Structure (Max 15) ----------------
        # Split: Fresh Issue % (Max 10) + Issue Size (Max 5)
        total_size = ipo.issue_size_crores
        fresh_size = ipo.fresh_issue_crores
        ofs_size = ipo.ofs_crores

        fresh_pts = 0.0
        fresh_ratio = None
        if total_size and total_size > 0:
            if fresh_size is not None:
                fresh_ratio = fresh_size / total_size
            elif ofs_size is not None:
                fresh_ratio = max(0.0, (total_size - ofs_size) / total_size)

        if fresh_ratio is not None:
            inputs_present["fresh_issue"] = True
            if fresh_ratio >= 0.75:
                fresh_pts = 10.0
                positive_factors.append(f"{fresh_ratio*100:.0f}% fresh issue proceeds intended for business expansion.")
            elif fresh_ratio >= 0.40:
                fresh_pts = 7.5
            elif fresh_ratio >= 0.15:
                fresh_pts = 5.0
                risk_factors.append(f"Significant Offer for Sale component ({((1-fresh_ratio)*100):.0f}% OFS).")
            else:
                fresh_pts = 2.0
                risk_factors.append("Predominantly Offer for Sale (OFS); proceeds go to selling shareholders rather than company.")
        else:
            fresh_pts = 0.0
            missing_inputs.append("Fresh Issue Ratio")

        size_pts = 0.0
        if total_size and total_size > 0:
            inputs_present["issue_size"] = True
            if is_sme:
                if 15.0 <= total_size <= 60.0:
                    size_pts = 5.0
                elif total_size > 60.0:
                    size_pts = 4.0
                else:
                    size_pts = 3.0
            else:
                if 300.0 <= total_size <= 5000.0:
                    size_pts = 5.0
                elif 100.0 <= total_size < 300.0:
                    size_pts = 4.0
                elif total_size > 5000.0:
                    size_pts = 3.5
                else:
                    size_pts = 3.0
        else:
            size_pts = 0.0
            missing_inputs.append("Issue Size")

        structure_score = min(15.0, fresh_pts + size_pts)

        # ---------------- Advanced Financial Health & Trend Analysis ----------------
        rev_growth = getattr(ipo, "revenue_growth_yoy", None)
        pat_growth = getattr(ipo, "pat_growth_yoy", None)

        if pat_growth is not None:
            if pat_growth <= -100.0 or (pat_margin is not None and pat_margin < 0 and pat_growth < 0):
                risk_factors.append("Profitability: PAT swung to a loss.")
            elif pat_growth < 0.0:
                risk_factors.append(f"Profitability: PAT declined {abs(pat_growth):.1f}% YoY.")
            elif pat_growth >= 25.0:
                positive_factors.append(f"Strong Profit Trajectory: PAT surged +{pat_growth:.1f}% YoY.")
            elif pat_growth < 10.0:
                risk_factors.append(f"Sluggish Profit Momentum: PAT grew only +{pat_growth:.1f}% YoY.")

        if rev_growth is not None:
            if rev_growth < 0.0:
                risk_factors.append(f"Top-line Contraction: Revenue declined {abs(rev_growth):.1f}% YoY.")
            elif rev_growth >= 20.0:
                positive_factors.append(f"Top-line Expansion: Revenue grew +{rev_growth:.1f}% YoY.")
            elif rev_growth < 5.0:
                risk_factors.append(f"Top-line Deceleration: Revenue growth slowed to +{rev_growth:.1f}% YoY.")

        if pat_margin is not None and pat_margin < 0:
            risk_factors.append(f"Negative Profit Margin: Net PAT Margin of {pat_margin:.1f}% reflects loss-making operations.")

        # ---------------- Normalization & Proportional Scaling ----------------
        available_max_weight = 0.0
        if inputs_present["gmp"]:
            available_max_weight += 35.0
        if inputs_present["subscription"]:
            available_max_weight += 30.0
        if inputs_present["pe"]:
            available_max_weight += 12.0
        if inputs_present["ronw"]:
            available_max_weight += 8.0
        if inputs_present["fresh_issue"]:
            available_max_weight += 10.0
        if inputs_present["issue_size"]:
            available_max_weight += 5.0

        evaluated_points = gmp_score + subscription_score + valuation_score + structure_score
        confidence = round(available_max_weight / 100.0, 2)
        confidence_pct = round(confidence * 100.0, 1)

        if available_max_weight > 0:
            composite_score = round((evaluated_points / available_max_weight) * 100.0, 1)
        else:
            composite_score = 0.0

        composite_score = max(0.0, min(100.0, composite_score))

        # Factor counts (4 factors: GMP, Subscription, Valuation, Structure)
        factors_evaluated_count = sum([
            inputs_present["gmp"],
            inputs_present["subscription"],
            (inputs_present["pe"] or inputs_present["ronw"]),
            (inputs_present["fresh_issue"] or inputs_present["issue_size"])
        ])

        # ---------------- Recommendation Rules ----------------
        derived_status = derive_ipo_status(ipo.open_date, ipo.close_date, ipo.listing_date)
        is_closed_or_listed = (derived_status in (IPOStatus.CLOSED, IPOStatus.LISTED)) or (ipo.close_date and today > ipo.close_date)

        if confidence < 0.50:
            recommendation = RecommendationType.INSUFFICIENT_DATA
            missing_str = ", ".join(missing_inputs) if missing_inputs else "Unknown factors"
            summary_statement = f"Insufficient Data - Based on {factors_evaluated_count} of 4 factors (Confidence: {confidence_pct}%). Missing: {missing_str}."
        else:
            if composite_score >= 75.0:
                raw_rec = RecommendationType.STRONG_APPLY
                raw_summary = "Strong conviction opportunity backed by robust grey market premium, heavy subscription interest, or sound fundamentals."
            elif composite_score >= 60.0:
                raw_rec = RecommendationType.APPLY
                raw_summary = "Favourable risk-reward ratio with healthy demand indicators and reasonable valuation."
            elif composite_score >= 45.0:
                raw_rec = RecommendationType.NEUTRAL
                raw_summary = "Neutral - Mixed signals; consider applying only if retail subscription or GMP accelerates closer to closing date."
            else:
                raw_rec = RecommendationType.AVOID
                raw_summary = "Avoid - Unfavourable risk-reward ratio due to muted demand, negative/negligible GMP, or elevated valuation."

            if is_extreme_gmp and raw_rec in (RecommendationType.STRONG_APPLY, RecommendationType.APPLY):
                raw_rec = RecommendationType.APPLY_VERIFY_GMP
                raw_summary = f"Extreme GMP ({gmp_pct:.1f}% of issue price exceeds 50%). Apply, verify GMP before relying on listing gains."

            if is_closed_or_listed:
                final_sub = f"{latest_subscription.total_multiple:.1f}x" if latest_subscription and latest_subscription.total_multiple else "—"
                listing_info = ipo.__dict__.get("listing_info")
                listing_g = f"{listing_info.listing_gain_pct:+.1f}%" if (listing_info and getattr(listing_info, "listing_gain_pct", None) is not None) else None
                sub_detail = f"Final Subscription: {final_sub}" + (f", Listing: {listing_g}" if listing_g else "")

                if raw_rec in (RecommendationType.STRONG_APPLY, RecommendationType.APPLY, RecommendationType.APPLY_VERIFY_GMP):
                    recommendation = RecommendationType.NEUTRAL
                    summary_statement = f"Issue Closed ({sub_detail}). Apply window has concluded."
                else:
                    recommendation = raw_rec
                    summary_statement = f"Issue Closed ({sub_detail}). {raw_summary}"
            else:
                recommendation = raw_rec
                summary_statement = raw_summary

        # Separate specific pillar reasons
        gmp_reasons = [f for f in positive_factors + risk_factors if any(k in f for k in ["Grey Market", "GMP", "Subject-to-Sauda"])]
        sub_reasons = [f for f in positive_factors + risk_factors if any(k in f for k in ["QIB", "retail", "Retail", "subscription", "oversubscription", "undersubscribed", "Bidding"])]
        val_reasons = [f for f in positive_factors + risk_factors if any(k in f for k in ["P/E", "valuation", "Valuation", "RoNW", "Net Worth", "Loss-making", "pricing", "Margin", "PAT", "Revenue", "Profit", "Top-line", "Debt"])]
        struct_reasons = [f for f in positive_factors + risk_factors if any(k in f for k in ["fresh", "Fresh", "OFS", "Offer for Sale", "issue size", "Issue size", "Sweet Spot", "Micro-Cap", "Promoter", "SME Segment"])]

        gmp_avail_max = 35.0 if inputs_present["gmp"] else 0.0
        sub_avail_max = 30.0 if inputs_present["subscription"] else 0.0
        val_avail_max = (12.0 if inputs_present["pe"] else 0.0) + (8.0 if inputs_present["ronw"] else 0.0)
        struct_avail_max = (10.0 if inputs_present["fresh_issue"] else 0.0) + (5.0 if inputs_present["issue_size"] else 0.0)

        pillars = {
            "gmp": {
                "name": "Grey Market Premium (GMP)",
                "score": round(gmp_score, 2),
                "max_score": gmp_avail_max if gmp_avail_max > 0 else 35.0,
                "percentage": round((gmp_score / gmp_avail_max) * 100, 1) if gmp_avail_max > 0 else 0.0,
                "present": inputs_present["gmp"],
                "reasons": gmp_reasons or (["GMP metric not available."] if not inputs_present["gmp"] else ["Baseline neutral market assumption."])
            },
            "subscription": {
                "name": "Subscription Demand",
                "score": round(subscription_score, 2),
                "max_score": sub_avail_max if sub_avail_max > 0 else 30.0,
                "percentage": round((subscription_score / sub_avail_max) * 100, 1) if sub_avail_max > 0 else 0.0,
                "present": inputs_present["subscription"],
                "reasons": sub_reasons or (["Subscription data not available."] if not inputs_present["subscription"] else ["Standard category participation."])
            },
            "valuation": {
                "name": "Valuation & Financials",
                "score": round(valuation_score, 2),
                "max_score": val_avail_max if val_avail_max > 0 else 20.0,
                "percentage": round((valuation_score / val_avail_max) * 100, 1) if val_avail_max > 0 else 0.0,
                "present": (inputs_present["pe"] or inputs_present["ronw"] or is_loss_making),
                "reasons": val_reasons or (["Valuation data not available."] if not (inputs_present["pe"] or inputs_present["ronw"] or is_loss_making) else ["Fair valuation relative to peers."])
            },
            "structure": {
                "name": "Issue Structure",
                "score": round(structure_score, 2),
                "max_score": struct_avail_max if struct_avail_max > 0 else 15.0,
                "percentage": round((structure_score / struct_avail_max) * 100, 1) if struct_avail_max > 0 else 0.0,
                "present": (inputs_present["fresh_issue"] or inputs_present["issue_size"]),
                "reasons": struct_reasons or (["Issue structure details missing."] if not (inputs_present["fresh_issue"] or inputs_present["issue_size"]) else ["Standard capital issue structure."])
            }
        }

        is_data_incomplete = (confidence < 0.80)

        rationale = {
            "summary": summary_statement,
            "data_incomplete": is_data_incomplete,
            "is_extreme_gmp": is_extreme_gmp,
            "confidence": confidence,
            "confidence_pct": confidence_pct,
            "available_max_weight": available_max_weight,
            "evaluated_points": round(evaluated_points, 2),
            "factors_evaluated_count": factors_evaluated_count,
            "factors_summary": f"based on {factors_evaluated_count} of 4 factors",
            "missing_inputs": missing_inputs,
            "weights": {
                "gmp_weight_max": max_gmp_pts,
                "subscription_weight_max": max_sub_pts,
                "valuation_weight_max": 20.0,
                "structure_weight_max": 15.0
            },
            "pillars": pillars,
            "positive_factors": positive_factors,
            "risk_factors": risk_factors,
            "metrics_snapshot": {
                "gmp_percentage": gmp_pct,
                "total_subscription": latest_subscription.total_multiple if latest_subscription else None,
                "qib_subscription": latest_subscription.qib_multiple if latest_subscription else None,
                "pe_ratio": ("not meaningful" if is_loss_making else ipo.pe_ratio),
                "is_pe_not_meaningful": is_loss_making,
                "industry_pe": ipo.industry_pe,
                "ronw": ipo.ronw,
                "issue_size_crores": ipo.issue_size_crores,
                "is_sme": is_sme
            }
        }

        return {
            "composite_score": composite_score,
            "recommendation": recommendation,
            "data_incomplete": is_data_incomplete,
            "confidence": confidence,
            "confidence_pct": confidence_pct,
            "missing_inputs": missing_inputs,
            "factors_evaluated_count": factors_evaluated_count,
            "gmp_score": round(gmp_score, 2),
            "subscription_score": round(subscription_score, 2),
            "valuation_score": round(valuation_score, 2),
            "structure_score": round(structure_score, 2),
            "rationale": rationale
        }

    @classmethod
    def calculate_synthetic(
        cls,
        ipo_type: str = "MAINBOARD",
        gmp_pct: Optional[float] = None,
        subject_to_sauda: Optional[float] = None,
        qib_multiple: Optional[float] = None,
        retail_multiple: Optional[float] = None,
        total_multiple: Optional[float] = None,
        day_number: Optional[int] = 3,
        pe_ratio: Optional[float] = None,
        industry_pe: Optional[float] = None,
        ronw: Optional[float] = None,
        fresh_issue_pct: Optional[float] = None,
        issue_size_crores: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates a score and pillar breakdown for simulated or what-if inputs from the Score Calculator.
        Uses the exact same scoring logic and thresholds.
        """
        is_sme = str(ipo_type).upper() == "SME"
        enum_type = IPOType.SME if is_sme else IPOType.MAINBOARD

        # Compute simulated fresh and OFS sizes if fresh_issue_pct is provided
        size = issue_size_crores or 500.0
        fresh_size = None
        ofs_size = None
        if fresh_issue_pct is not None:
            pct_norm = max(0.0, min(100.0, fresh_issue_pct)) / 100.0
            fresh_size = size * pct_norm
            ofs_size = size * (1.0 - pct_norm)

        # Mock IPO
        dummy_ipo = IPO(
            symbol="CALC_SIM",
            company_name="Calculator Simulation Ltd",
            ipo_type=enum_type,
            issue_price=100.0,
            issue_size_crores=size,
            fresh_issue_crores=fresh_size,
            ofs_crores=ofs_size,
            pe_ratio=pe_ratio,
            industry_pe=industry_pe,
            ronw=ronw
        )

        # Mock GMP
        dummy_gmp = None
        if gmp_pct is not None or subject_to_sauda is not None:
            dummy_gmp = IPOGmp(
                ipo_id=0,
                gmp_amount=(gmp_pct or 0.0),
                gmp_percentage=gmp_pct if gmp_pct is not None else 0.0,
                subject_to_sauda=subject_to_sauda
            )

        # Mock Subscription
        dummy_sub = None
        if any(v is not None for v in [qib_multiple, retail_multiple, total_multiple]):
            dummy_sub = IPOSubscription(
                ipo_id=0,
                qib_multiple=qib_multiple,
                retail_multiple=retail_multiple,
                total_multiple=total_multiple if total_multiple is not None else (qib_multiple or 0.0) + (retail_multiple or 0.0),
                day_number=day_number or 3
            )

        score_res = cls.calculate_score(dummy_ipo, dummy_sub, dummy_gmp)
        return {
            **score_res,
            "pillars": score_res["rationale"]["pillars"]
        }
