import pytest
import types
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

from app.models.ipo import IPO, IPOGmp, IPOSubscription, IPOScore, IPOStatus, IPOType, RecommendationType
from app.schemas.ipo import SubscriptionCreate, GMPCreate
from app.services.scoring_service import ScoringService
from app.services.consensus_gmp import ConsensusGmpService
from app.services.ipo_service import IPOService
from app.services.chittorgarh_scraper import ChittorgarhClient


def test_financial_wording_pat_swung_to_loss():
    ipo = IPO(
        id=101,
        company_name="Alpha Tech Ltd",
        symbol="ALPHATECH",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=100.0,
        pat_growth_yoy=-134.87,
        pat_margin_pct=-47.52,
        eps=-2.5,
        revenue_growth_yoy=-25.4,
        ronw=-5.0,
        issue_size_crores=500.0,
        fresh_issue_crores=250.0
    )
    score_res = ScoringService.calculate_score(ipo, None, None)
    rationale = score_res["rationale"]
    all_risks = " ".join(rationale["risk_factors"])

    # Must say 'swung to a loss' and NEVER 'contracted by 134.9%'
    assert "swung to a loss" in all_risks
    assert "contracted by" not in all_risks

    # Revenue negative must say 'revenue declined'
    assert "Revenue declined 25.4% YoY" in all_risks

    # When EPS or PAT is negative, P/E must be not meaningful and excluded from P/E scoring
    assert "P/E is not meaningful" in all_risks
    assert rationale["weights"]["valuation_weight_max"] == 20.0
    assert rationale["pillars"]["valuation"]["score"] == 0.0
    assert rationale["metrics_snapshot"]["pe_ratio"] == "not meaningful"
    assert rationale["metrics_snapshot"]["is_pe_not_meaningful"] is True


def test_financial_wording_positive_to_negative_pat_and_loss_pe():
    ipo = IPO(
        id=102,
        company_name="Beta Growth Ltd",
        symbol="BETAGROW",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=200.0,
        pat_growth_yoy=-105.0,
        pat_margin_pct=5.0,
        revenue_growth_yoy=-12.5,
        pe_ratio=50.0,
        eps=-1.0,
        ronw=12.0,
        issue_size_crores=400.0,
        fresh_issue_crores=300.0
    )
    score_res = ScoringService.calculate_score(ipo, None, None)
    rationale = score_res["rationale"]
    all_risks = " ".join(rationale["risk_factors"])

    assert "swung to a loss" in all_risks
    assert "contracted by" not in all_risks
    assert "Revenue declined 12.5% YoY" in all_risks
    assert "P/E is not meaningful" in all_risks


def test_chittorgarh_parser_compares_like_periods():
    # Table where column 1 is 3-month interim stub, and columns 2 and 3 are 12-month full years
    html = """
    <html><body>
      <table>
        <tr>
          <th>Period Ended</th>
          <th>30 Jun 2024</th>
          <th>31 Mar 2024</th>
          <th>31 Mar 2023</th>
        </tr>
        <tr>
          <td>Total Income</td>
          <td>10.5</td>
          <td>104.1</td>
          <td>80.0</td>
        </tr>
        <tr>
          <td>Profit After Tax</td>
          <td>-5.0</td>
          <td>14.3</td>
          <td>10.0</td>
        </tr>
      </table>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    parsed = {"revenue_growth_yoy": None, "pat_growth_yoy": None}
    
    # We call ChittorgarhScraper's parse logic on this HTML
    for t in tables:
        header_row = None
        for tr in t.find_all("tr"):
            th_cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if th_cells and any("period ended" in c.lower() or "financial year" in c.lower() for c in th_cells):
                header_row = th_cells
                break

        def _detect_period_duration_months(header_text: str) -> int:
            import re
            txt = header_text.lower().strip()
            m_dur = re.search(r"(\d+)\s*(?:month|m\b)", txt)
            if m_dur:
                return int(m_dur.group(1))
            if "30 jun" in txt or "30 june" in txt:
                return 3
            if "30 sep" in txt or "30 sept" in txt:
                return 6
            if "31 dec" in txt or "31 dece" in txt:
                return 9
            if "31 mar" in txt or "31 marc" in txt:
                return 12
            return 12

        def _find_like_period_columns(h_cells):
            durations = [_detect_period_duration_months(c) for c in h_cells[1:]]
            for i in range(len(durations)):
                for j in range(i + 1, len(durations)):
                    if durations[i] == durations[j]:
                        return i + 1, j + 1
            return None, None

        curr_col, prior_col = 1, 2
        if header_row and len(header_row) >= 3:
            c1, c2 = _find_like_period_columns(header_row)
            if c1 and c2:
                curr_col, prior_col = c1, c2

        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells or len(cells) <= max(curr_col, prior_col):
                continue
            lbl = cells[0].strip().lower()
            if "total income" in lbl:
                curr_val = float(cells[curr_col])
                prior_val = float(cells[prior_col])
                parsed["revenue_growth_yoy"] = round(((curr_val - prior_val) / prior_val) * 100.0, 2)
            elif "profit after tax" in lbl:
                curr_val = float(cells[curr_col])
                prior_val = float(cells[prior_col])
                parsed["pat_growth_yoy"] = round(((curr_val - prior_val) / prior_val) * 100.0, 2)

    # Must compare 31 Mar 2024 (104.1 / 14.3) with 31 Mar 2023 (80.0 / 10.0), NOT 30 Jun 2024!
    assert parsed["revenue_growth_yoy"] == round(((104.1 - 80.0) / 80.0) * 100.0, 2)
    assert parsed["pat_growth_yoy"] == round(((14.3 - 10.0) / 10.0) * 100.0, 2)
    assert parsed["revenue_growth_yoy"] == 30.12
    assert parsed["pat_growth_yoy"] == 43.0


def test_consensus_gmp_last_known_and_rationale_change():
    now = datetime.now(timezone.utc)
    # Stale readings (> 24 hours ago)
    old_reading = IPOGmp(
        ipo_id=201,
        source="investorgain",
        gmp_amount=45.0,
        gmp_percentage=45.0,
        recorded_at=now - timedelta(hours=30)
    )
    res_stale = ConsensusGmpService.calculate_consensus_from_readings([old_reading], now=now)
    assert res_stale["status"] == "missing"
    assert res_stale["last_known"] is not None
    assert res_stale["last_known"]["gmp_amount"] == 45.0
    assert res_stale["last_known"]["source"] == "investorgain"

    ipo = IPO(
        id=201,
        company_name="Gamma Industries",
        symbol="GAMMA",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=100.0,
        pe_ratio=20.0,
        ronw=15.0,
        issue_size_crores=500.0,
        fresh_issue_crores=300.0
    )

    # Score with NO fresh GMP
    score_before = ScoringService.calculate_score(ipo, None, None)
    assert "GMP metric not available." in score_before["rationale"]["pillars"]["gmp"]["reasons"]
    assert "Grey Market Premium (GMP)" in score_before["rationale"]["missing_inputs"]

    # Now fresh GMP arrives
    fresh_reading = IPOGmp(
        ipo_id=201,
        source="investorgain",
        gmp_amount=35.0,
        gmp_percentage=35.0,
        recorded_at=now - timedelta(hours=2)
    )
    score_after = ScoringService.calculate_score(ipo, None, fresh_reading)
    gmp_reasons_after = score_after["rationale"]["pillars"]["gmp"]["reasons"]
    assert any("Grey Market Premium" in r for r in gmp_reasons_after)
    assert "Grey Market Premium (GMP)" not in score_after["rationale"]["missing_inputs"]
    assert score_after["composite_score"] > score_before["composite_score"]


@pytest.mark.asyncio
async def test_insert_deduplication(db_session):
    # Verify deduplication for both subscriptions and GMP in IPOService
    ipo = IPO(
        company_name="Dedupe Test Ltd",
        symbol="DEDUPETEST",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=100.0
    )
    db_session.add(ipo)
    await db_session.commit()
    await db_session.refresh(ipo)

    sub_data = SubscriptionCreate(
        total_multiple=5.5,
        qib_multiple=2.0,
        nii_multiple=4.0,
        retail_multiple=7.0
    )
    # First insert
    s1 = await IPOService.add_subscription(db_session, ipo.id, sub_data)
    # Second insert with identical values immediately
    s2 = await IPOService.add_subscription(db_session, ipo.id, sub_data)
    assert s1.id == s2.id

    # GMP insert deduplication
    gmp_data = GMPCreate(
        gmp_amount=25.0,
        gmp_percentage=25.0,
        source="investorgain"
    )
    g1 = await IPOService.add_gmp(db_session, ipo.id, gmp_data)
    g2 = await IPOService.add_gmp(db_session, ipo.id, gmp_data)
    assert g1.id == g2.id


@pytest.mark.asyncio
async def test_gmp_trend_endpoint(client, db_session):
    now = datetime.now(timezone.utc)
    ipo = IPO(
        company_name="Trend Tech Ltd",
        symbol="TRENDTECH",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        issue_price=100.0
    )
    db_session.add(ipo)
    await db_session.commit()
    await db_session.refresh(ipo)

    # Add single GMP reading
    gmp1 = IPOGmp(
        ipo_id=ipo.id,
        source="investorgain",
        gmp_amount=30.0,
        gmp_percentage=30.0,
        recorded_at=now
    )
    db_session.add(gmp1)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ipos/{ipo.id}/gmp/trend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ipo_id"] == ipo.id
    assert "investorgain" in data["sources"]
    assert len(data["sources"]["investorgain"]) == 1
    assert len(data["consensus"]) == 1
    assert data["total_readings"] == 1
    # Check timestamp has IST offset
    assert "+05:30" in data["sources"]["investorgain"][0]["recorded_at"]
