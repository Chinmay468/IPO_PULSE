from datetime import date
from typing import Optional, Dict, Any, List
from app.models.ipo import IPO, IPOSubscription, IPOGmp, IPOType, RecommendationType


class ScoringService:
    @staticmethod
    def calculate_score(
        ipo: IPO,
        latest_subscription: Optional[IPOSubscription] = None,
        latest_gmp: Optional[IPOGmp] = None
    ) -> Dict[str, Any]:
        """
        Computes an institutional-grade multi-parameter composite score (0-100) and recommendation:
        - 1. GMP Component (max 35) with SME vs Mainboard tier calibrations & market depth
        - 2. Subscription Component (max 30) with Day-of-bidding awareness & category dynamics
        - 3. Valuation & Financials (max 20) with P/E vs Industry, RoNW capital efficiency & loss-maker handling
        - 4. Issue Structure (max 15) with Fresh Issue % vs OFS and liquidity sweet-spot scaling
        """
        positive_factors: List[str] = []
        risk_factors: List[str] = []

        is_sme = (ipo.ipo_type == IPOType.SME)
        today = date.today()

        # ---------------- 1. GMP Component (Max 35) ----------------
        gmp_score = 0.0
        gmp_pct: Optional[float] = None

        if latest_gmp:
            gmp_pct = latest_gmp.gmp_percentage
            # If percentage not explicitly provided, calculate using issue price or upper band
            if (gmp_pct is None or gmp_pct == 0) and (latest_gmp.gmp_amount is not None and latest_gmp.gmp_amount > 0):
                base_price = ipo.issue_price or ipo.price_band_high or ipo.price_band_low
                if base_price and base_price > 0:
                    gmp_pct = (latest_gmp.gmp_amount / base_price) * 100

        if gmp_pct is not None:
            # Calibrated thresholds: Mainboard bumper listing starts at 35%+, SME at 50%+
            bumper_cutoff = 50.0 if is_sme else 35.0
            strong_cutoff = 30.0 if is_sme else 20.0
            healthy_cutoff = 15.0 if is_sme else 10.0

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

            # Bonus for Kostak / Subject-to-sauda demand if recorded
            if latest_gmp.subject_to_sauda and latest_gmp.subject_to_sauda > 0:
                positive_factors.append(f"Active Subject-to-Sauda premium (₹{latest_gmp.subject_to_sauda:.0f}) confirms firm retail buyer interest.")
                gmp_score = min(35.0, gmp_score + 1.5)
        else:
            # Baseline neutral estimation when GMP has not developed yet
            gmp_score = 15.0
            risk_factors.append("No active Grey Market Premium recorded yet; score reflects baseline neutral assumption.")

        # ---------------- 2. Subscription Component (Max 30) ----------------
        subscription_score = 0.0
        if latest_subscription:
            qib = latest_subscription.qib_multiple
            retail = latest_subscription.retail_multiple
            total = latest_subscription.total_multiple

            # Determine bidding timeline context (Day 1/2 vs Final Day)
            is_early_bidding = False
            if latest_subscription.day_number and latest_subscription.day_number < 3:
                is_early_bidding = True
            elif ipo.open_date and today <= (ipo.open_date if hasattr(ipo.open_date, '__add__') else today):
                is_early_bidding = True

            # QIB Component (Max 16 pts) - Institutional endorsement
            qib_pts = 0.0
            qib_target = 60.0 if is_sme else 30.0

            if qib is not None:
                if qib >= qib_target:
                    qib_pts = 16.0
                    positive_factors.append(f"Massive institutional interest with QIB subscribed {qib:.1f}x.")
                elif qib >= (qib_target * 0.5):
                    qib_pts = 13.0
                    positive_factors.append(f"Strong QIB subscription of {qib:.1f}x demonstrates solid institutional backing.")
                elif qib >= 5.0:
                    qib_pts = 10.0
                    positive_factors.append(f"Healthy QIB subscription of {qib:.1f}x.")
                elif qib >= 1.0:
                    qib_pts = 6.0
                else:
                    if is_early_bidding:
                        # In India, QIBs almost exclusively bid on Day 3 afternoon. Do not prematurely penalize.
                        qib_pts = 5.0
                        positive_factors.append(f"Bidding in progress ({'Day ' + str(latest_subscription.day_number) if latest_subscription.day_number else 'initial window'}); institutional QIB surge expected on closing day.")
                    else:
                        qib_pts = 1.0
                        risk_factors.append(f"Subdued QIB institutional demand ({qib:.2f}x).")
            else:
                qib_pts = 5.0 if is_early_bidding else 3.0

            # Retail Component (Max 6 pts) - Broad public interest
            retail_pts = 0.0
            retail_target = 25.0 if is_sme else 10.0

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
            else:
                retail_pts = 2.0

            # Overall Subscription Multiple (Max 8 pts)
            total_pts = 0.0
            total_target = 50.0 if is_sme else 35.0

            if total is not None:
                if total >= total_target:
                    total_pts = 8.0
                    positive_factors.append(f"Huge overall oversubscription of {total:.1f}x.")
                elif total >= (total_target * 0.4):
                    total_pts = 6.5
                    positive_factors.append(f"Healthy total subscription of {total:.1f}x.")
                elif total >= 3.0:
                    total_pts = 5.0
                elif total >= 1.0:
                    total_pts = 3.0
                else:
                    total_pts = 0.5
                    if not is_early_bidding:
                        risk_factors.append(f"Total issue undersubscribed ({total:.2f}x).")
            else:
                total_pts = 2.0

            subscription_score = min(30.0, qib_pts + retail_pts + total_pts)
        else:
            # For upcoming or newly opened IPOs before bidding numbers update
            subscription_score = 15.0

        # ---------------- 3. Valuation & Financials (Max 20) ----------------
        valuation_score = 0.0
        pe = ipo.pe_ratio
        ind_pe = ipo.industry_pe
        ronw = ipo.ronw

        # PE vs Industry PE (Max 12 pts)
        pe_pts = 6.0  # default
        if pe is not None and ind_pe is not None and ind_pe > 0:
            if pe > 0:
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
                # Loss making (P/E < 0) e.g., tech new-age IPOs
                pe_pts = 2.0
                risk_factors.append("Loss-making operations (negative P/E ratio).")
        elif pe is not None and pe > 0:
            if pe < 25:
                pe_pts = 9.0
            elif pe < 45:
                pe_pts = 6.5
            else:
                pe_pts = 3.0
                risk_factors.append(f"High absolute P/E multiple ({pe:.1f}).")

        # RoNW (Return on Net Worth) (Max 8 pts)
        ronw_pts = 4.0  # default
        if ronw is not None:
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

        valuation_score = min(20.0, pe_pts + ronw_pts)

        # ---------------- 4. Issue Structure (Max 15) ----------------
        structure_score = 0.0
        total_size = ipo.issue_size_crores
        fresh_size = ipo.fresh_issue_crores
        ofs_size = ipo.ofs_crores

        # Fresh Issue Ratio (Max 10 pts)
        if total_size and total_size > 0:
            if fresh_size is not None:
                fresh_ratio = fresh_size / total_size
            elif ofs_size is not None:
                fresh_ratio = max(0.0, (total_size - ofs_size) / total_size)
            else:
                fresh_ratio = 0.5

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
            fresh_pts = 6.5

        # Issue Size & Market Liquidity Comfort (Max 5 pts)
        size_pts = 3.5
        if total_size:
            if is_sme:
                # SME Liquidity Sweet Spot: ₹15 Cr to ₹60 Cr
                if 15.0 <= total_size <= 60.0:
                    size_pts = 5.0
                elif total_size > 60.0:
                    size_pts = 4.0
                else:
                    size_pts = 3.0
            else:
                # Mainboard Liquidity Sweet Spot: ₹300 Cr to ₹5,000 Cr
                if 300.0 <= total_size <= 5000.0:
                    size_pts = 5.0
                elif total_size > 5000.0:
                    size_pts = 3.5
                elif total_size < 100.0:
                    size_pts = 3.0

        structure_score = min(15.0, fresh_pts + size_pts)

        # ---------------- Advanced Financial Health & Trend Analysis ----------------
        # 1. Revenue & PAT Momentum
        rev_growth = getattr(ipo, "revenue_growth_yoy", None)
        pat_growth = getattr(ipo, "pat_growth_yoy", None)
        d_to_e = getattr(ipo, "debt_to_equity", None)
        margin = getattr(ipo, "pat_margin_pct", None)
        promoter_post = getattr(ipo, "promoter_holding_post", None)
        sector = getattr(ipo, "sector", None)

        if pat_growth is not None:
            if pat_growth >= 25.0:
                positive_factors.append(f"Strong Profit Trajectory: PAT surged +{pat_growth:.1f}% YoY demonstrating solid operating leverage.")
            elif pat_growth <= 0.0:
                risk_factors.append(f"Earnings Contraction: Net profit contracted by {abs(pat_growth):.1f}% YoY.")
            elif pat_growth < 10.0:
                risk_factors.append(f"Sluggish Profit Momentum: PAT grew only +{pat_growth:.1f}% YoY.")

        if rev_growth is not None:
            if rev_growth >= 20.0:
                positive_factors.append(f"Top-line Expansion: Revenue grew +{rev_growth:.1f}% YoY indicating expanding market footprint.")
            elif rev_growth < 5.0:
                risk_factors.append(f"Top-line Deceleration: Revenue growth slowed to {rev_growth:.1f}% YoY.")

        # 2. Leverage & Balance Sheet Strength
        if d_to_e is not None:
            if d_to_e <= 0.35:
                positive_factors.append(f"Conservative Leverage: Low Debt/Equity of {d_to_e:.2f}x provides strong balance sheet resilience.")
            elif d_to_e >= 1.2:
                risk_factors.append(f"High Debt Burden: Debt/Equity of {d_to_e:.2f}x carries elevated interest servicing obligations.")

        # 3. Margin Quality
        if margin is not None:
            if margin >= 12.0:
                positive_factors.append(f"High Margin Profile: Healthy Net PAT Margin of {margin:.1f}%.")
            elif margin < 4.5:
                risk_factors.append(f"Thin Margin Cushion: Low PAT Margin of {margin:.1f}% is vulnerable to input cost spikes.")

        # 4. Promoter Commitment
        if promoter_post is not None:
            if promoter_post >= 65.0:
                positive_factors.append(f"High Promoter Skin-in-the-Game: Promoters maintain strong {promoter_post:.1f}% post-issue stake.")
            elif promoter_post < 45.0:
                risk_factors.append(f"Diluted Promoter Holding: Post-issue promoter stake reduces to {promoter_post:.1f}%.")

        # 5. Sector & Business Dynamics
        if sector:
            sec_lower = sector.lower()
            if "gems" in sec_lower or "jewel" in sec_lower:
                risk_factors.append("Working Capital Intensity: High inventory carrying periods and precious metal raw material volatility.")
            elif "infra" in sec_lower or "construct" in sec_lower:
                risk_factors.append("Execution & Project Risk: Dependent on timely order-book execution and government approvals.")
            elif "tech" in sec_lower or "software" in sec_lower:
                positive_factors.append("Asset-Light Scalability: High operational leverage with minimal heavy machinery capex.")

        # ---------------- Structural & Segment Risk Disclosures ----------------
        if is_sme:
            lot_val = ((ipo.issue_price or ipo.price_band_high or 100.0) * (ipo.lot_size or 1000)) / 100000.0
            risk_factors.append(
                f"SME Segment Liquidity & Lot Size: Minimum application ticket of ~₹{lot_val:.2f} Lakhs and mandatory lot-based secondary trading."
            )

        if not risk_factors:
            risk_factors.append("Listing Volatility: Grey Market Premium (GMP) is informal OTC sentiment and can fluctuate with broader market movements prior to listing.")
            if total_size and total_size < 30.0:
                risk_factors.append("Micro-Cap Scale: Small issue size (< ₹30 Cr) carries inherent operational and client concentration dependencies.")

        # ---------------- Composite Calculation ----------------
        composite_score = round(gmp_score + subscription_score + valuation_score + structure_score, 2)
        composite_score = max(0.0, min(100.0, composite_score))

        # Determine Recommendation
        if composite_score >= 75.0:
            recommendation = RecommendationType.STRONG_APPLY
            summary_statement = "Strong Apply - High conviction opportunity backed by robust grey market premium, heavy subscription interest, or sound fundamentals."
        elif composite_score >= 60.0:
            recommendation = RecommendationType.APPLY
            summary_statement = "Apply - Favourable risk-reward ratio with healthy demand indicators and reasonable valuation."
        elif composite_score >= 45.0:
            recommendation = RecommendationType.NEUTRAL
            summary_statement = "Neutral - Mixed signals; consider applying only if retail subscription or GMP accelerates closer to closing date."
        else:
            recommendation = RecommendationType.AVOID
            summary_statement = "Avoid - Unfavourable risk-reward ratio due to muted demand, negative/negligible GMP, or elevated valuation."

        rationale = {
            "summary": summary_statement,
            "weights": {
                "gmp_weight_max": 35.0,
                "subscription_weight_max": 30.0,
                "valuation_weight_max": 20.0,
                "structure_weight_max": 15.0
            },
            "positive_factors": positive_factors,
            "risk_factors": risk_factors,
            "metrics_snapshot": {
                "gmp_percentage": gmp_pct,
                "total_subscription": latest_subscription.total_multiple if latest_subscription else None,
                "qib_subscription": latest_subscription.qib_multiple if latest_subscription else None,
                "pe_ratio": ipo.pe_ratio,
                "industry_pe": ipo.industry_pe,
                "ronw": ipo.ronw,
                "issue_size_crores": ipo.issue_size_crores,
                "is_sme": is_sme
            }
        }

        return {
            "composite_score": composite_score,
            "recommendation": recommendation,
            "gmp_score": round(gmp_score, 2),
            "subscription_score": round(subscription_score, 2),
            "valuation_score": round(valuation_score, 2),
            "structure_score": round(structure_score, 2),
            "rationale": rationale
        }
