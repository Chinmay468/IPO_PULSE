import pytest
from app.services.csv_import_service import parse_rows, parse_file


def test_parse_rows_rejects_missing_and_zero_buy_price():
    rows = [
        ["Symbol", "Quantity", "Average Price"],
        ["RELIANCE", "10", "2500.00"],
        ["TCS", "5", "0.0"],          # Zero buy price -> should be rejected
        ["INFY", "15", ""],           # Missing buy price -> should be rejected
        ["HDFCBANK", "0", "1600.00"], # Zero quantity -> should be rejected
        ["ITC", "20", "450.00"],      # Valid
    ]

    skipped = []
    results = parse_rows(rows, skipped_out=skipped)

    # Only RELIANCE and ITC should be accepted
    symbols = [r["symbol"] for r in results]
    assert symbols == ["RELIANCE", "ITC"]
    assert results[0]["avg_buy_price"] == 2500.00
    assert results[1]["avg_buy_price"] == 450.00

    # Ensure no default of 100.0 exists
    for r in results:
        assert r["avg_buy_price"] is not None
        assert r["avg_buy_price"] > 0

    # Check skipped reasons
    skipped_dict = {s["symbol"]: s["reason"] for s in skipped}
    assert "TCS" in skipped_dict
    assert "missing or zero buy price" in skipped_dict["TCS"]
    assert "INFY" in skipped_dict
    assert "missing or zero buy price" in skipped_dict["INFY"]
    assert "HDFCBANK" in skipped_dict
    assert "missing or zero quantity" in skipped_dict["HDFCBANK"]


def test_parse_file_csv_with_skipped_rows():
    csv_data = b"Symbol,Quantity,Average Price\nRELIANCE,10,2500.00\nWIPRO,50,0\n"
    skipped = []
    holdings = parse_file(csv_data, "test.csv", skipped_out=skipped)
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "RELIANCE"
    assert len(skipped) == 1
    assert skipped[0]["symbol"] == "WIPRO"
    assert "missing or zero buy price" in skipped[0]["reason"]
