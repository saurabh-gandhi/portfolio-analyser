"""
tests/test_basic.py
Basic smoke tests — no external network calls.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
from src.portfolio_loader import load_portfolio, _clean_numeric
from src.instrument_registry import classify_instrument, InstrumentType


# ── portfolio_loader ──────────────────────────────────────────────────────────

def test_clean_numeric():
    assert _clean_numeric("₹1,23,456") == 123456.0
    assert _clean_numeric("(500)") == -500.0
    assert _clean_numeric("0.00%") == 0.0
    assert _clean_numeric(None) == 0.0
    assert _clean_numeric("abc") == 0.0


def test_load_sample_portfolio():
    path = Path(__file__).parent.parent / "data/sample/portfolio_sample.csv"
    df = load_portfolio(str(path))
    assert len(df) > 0
    assert "Asset" in df.columns
    assert "Present Value" in df.columns
    assert df["Present Value"].sum() > 0
    assert (df["Present Value"] > 0).all()


# ── instrument_registry ───────────────────────────────────────────────────────

def test_classify_sgb():
    p = classify_instrument("SGBJAN29X-GB", 100000, "Gold", "Bond")
    assert p.instrument_type == InstrumentType.SGB


def test_classify_niftybees():
    p = classify_instrument("NIFTYBEES", 100000, "Equity", "ETF")
    assert p.instrument_type == InstrumentType.INDIAN_ETF
    assert p.amfi_family_id is not None


def test_classify_reit():
    p = classify_instrument("BIRET-RR", 100000, "Real Estate", "Stock")
    assert p.instrument_type == InstrumentType.REIT


def test_classify_us_etf():
    p = classify_instrument("QQQ", 100000, "Equity", "ETF")
    assert p.instrument_type == InstrumentType.US_ETF


def test_classify_direct_stock():
    p = classify_instrument("HDFCBANK", 100000, "Equity", "Stock")
    assert p.instrument_type == InstrumentType.DIRECT_STOCK_IN


def test_classify_epf():
    p = classify_instrument("Saurabh EPF", 100000, "Debt", "Providend fund")
    assert p.instrument_type == InstrumentType.EPF


def test_classify_ppf():
    p = classify_instrument("PPF", 100000, "Debt", "Providend fund")
    # PPF is detected from override config; falls back to EPF if not configured
    assert p.instrument_type in (InstrumentType.PPF, InstrumentType.EPF)


def test_classify_cash():
    p = classify_instrument("Bank - Axis", 100000, "Cash", "Cash")
    assert p.instrument_type == InstrumentType.BANK_ACCOUNT


def test_classify_us_stock():
    p = classify_instrument("NVDA", 100000, "Equity", "Stock")
    assert p.instrument_type == InstrumentType.DIRECT_STOCK_US


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
