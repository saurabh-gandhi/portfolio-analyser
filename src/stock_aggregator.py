"""
stock_aggregator.py
Aggregates constituent stock holdings across all MFs and ETFs
into a single stock-level view with weighted ₹ exposure.
"""

import re
import pandas as pd
from dataclasses import dataclass, field

from .holdings_fetcher import FundData, Holding
from .instrument_registry import InstrumentProfile, InstrumentType


@dataclass
class StockPosition:
    stock_name: str
    sector: str
    instruments_count: int
    held_in: str           # pipe-separated list of instruments
    total_rs_exposure: float
    pct_of_equity_pool: float
    pct_of_total_portfolio: float
    max_pct_in_any: float
    source_types: str


# ── Name normalisation ────────────────────────────────────────────────────────
_SUFFIXES = [" LIMITED", " LTD", " LTD.", " CORP", " CORPORATION",
             " INC", " INC.", " PLC", " CO.", " & CO"]

_OVERRIDES = {
    "HDFC BANK": "HDFC BANK", "ICICI BANK": "ICICI BANK",
    "AXIS BANK": "AXIS BANK", "STATE BANK OF INDIA": "STATE BANK OF INDIA",
    "BHARTI AIRTEL": "BHARTI AIRTEL", "INFOSYS": "INFOSYS",
    "RELIANCE INDUSTRIES": "RELIANCE INDUSTRIES",
    "KOTAK MAHINDRA BANK": "KOTAK MAHINDRA BANK",
    "HINDUSTAN UNILEVER": "HINDUSTAN UNILEVER",
    "TATA CONSULTANCY SERVICES": "TATA CONSULTANCY SERVICES",
    "NVIDIA CORP": "NVIDIA", "NVIDIA": "NVIDIA",
    "APPLE INC": "APPLE", "APPLE": "APPLE",
    "AMAZON.COM": "AMAZON", "AMAZON": "AMAZON",
    "MICROSOFT CORP": "MICROSOFT", "MICROSOFT": "MICROSOFT",
    "ALPHABET": "ALPHABET", "META PLATFORMS": "META",
}


def normalise_stock_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    n = str(name).strip().upper()
    for suffix in _SUFFIXES:
        n = n.replace(suffix, "")
    n = re.sub(r"\s+", " ", n).strip()
    for k, v in _OVERRIDES.items():
        if n.startswith(k):
            return v
    return n


def _best_sector(sectors: list[str]) -> str:
    sectors = [s for s in sectors if s and str(s) not in ("nan", "None", "")]
    preferred = [s for s in sectors if s in {
        "Financial Services", "Technology", "Consumer Cyclical", "Industrials",
        "Basic Materials", "Healthcare", "Consumer Defensive", "Energy",
        "Utilities", "Communication Services", "Real Estate", "Banks",
        "Pharmaceuticals & Biotechnology", "Automobiles",
    }]
    return preferred[0] if preferred else (sectors[0] if sectors else "")


def build_stock_rollup(profiles: list[InstrumentProfile],
                       holdings_map: dict[str, FundData],
                       total_portfolio_value: float,
                       exclude_arbitrage: bool = True) -> pd.DataFrame:
    """
    Build a stock-level rollup across all instruments.
    Returns a DataFrame with one row per unique (normalised) stock.
    """
    rows = []

    for profile in profiles:
        name = profile.asset_name
        pv = profile.present_value

        # Skip arbitrage funds from equity analysis
        if exclude_arbitrage and profile.instrument_type == InstrumentType.ARBITRAGE_MF:
            continue

        fd = holdings_map.get(name)
        if not fd or fd.error or not fd.equity_holdings:
            # Direct stocks / single-asset instruments
            if profile.instrument_type in (
                InstrumentType.DIRECT_STOCK_IN, InstrumentType.DIRECT_STOCK_US,
                InstrumentType.ESOP, InstrumentType.REIT,
            ):
                display_name = name
                source = "Direct Stock" if profile.instrument_type == InstrumentType.DIRECT_STOCK_IN else \
                         "US Stock" if profile.instrument_type == InstrumentType.DIRECT_STOCK_US else \
                         "ESOP" if profile.instrument_type == InstrumentType.ESOP else "REIT"
                rows.append({
                    "Norm": normalise_stock_name(name),
                    "Original Name": name,
                    "Sector": "",
                    "Instrument": name,
                    "Weight Pct": 100.0,
                    "Weighted Rs": pv,
                    "Source": source,
                })
            continue

        # MF/ETF with constituent data
        source_type = "MF Equity" if profile.instrument_type == InstrumentType.INDIAN_MF else "ETF"

        for holding in fd.equity_holdings:
            if not holding.stock_name:
                continue
            rows.append({
                "Norm": normalise_stock_name(holding.stock_name),
                "Original Name": holding.stock_name,
                "Sector": holding.sector,
                "Instrument": name,
                "Weight Pct": holding.weight_pct,
                "Weighted Rs": holding.market_value_rs,
                "Source": source_type,
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df["Norm"] != ""]

    # Aggregate
    agg = df.groupby("Norm").agg(
        Sector=("Sector", lambda x: _best_sector(list(x))),
        Instruments_Count=("Instrument", "nunique"),
        Held_In=("Instrument", lambda x: " | ".join(sorted(set(x)))),
        Total_Rs=("Weighted Rs", "sum"),
        Max_Pct=("Weight Pct", "max"),
        Source_Types=("Source", lambda x: " + ".join(sorted(set(x)))),
        Original_Names=("Original Name", lambda x: " / ".join(sorted(set(str(n) for n in x))[:3])),
    ).reset_index()

    equity_pool = agg["Total_Rs"].sum()
    agg["Pct of Equity Pool"] = (agg["Total_Rs"] / equity_pool * 100).round(4) if equity_pool > 0 else 0
    agg["Pct of Total Portfolio"] = (agg["Total_Rs"] / total_portfolio_value * 100).round(4)
    agg = agg.sort_values("Total_Rs", ascending=False).reset_index(drop=True)
    agg.insert(0, "Rank", range(1, len(agg) + 1))

    print(f"[stock_aggregator] {len(agg)} unique stocks, equity pool: ₹{equity_pool:,.0f}")
    return agg


def build_sector_rollup(stock_df: pd.DataFrame,
                        total_portfolio_value: float) -> pd.DataFrame:
    """Aggregate stock positions to sector level."""
    if stock_df.empty:
        return pd.DataFrame()

    sec = stock_df.groupby("Sector").agg(
        Stock_Count=("Norm", "nunique"),
        Total_Rs=("Total_Rs", "sum"),
    ).reset_index()

    equity_pool = stock_df["Total_Rs"].sum()
    sec["Pct of Equity Pool"] = (sec["Total_Rs"] / equity_pool * 100).round(2) if equity_pool > 0 else 0
    sec["Pct of Total Portfolio"] = (sec["Total_Rs"] / total_portfolio_value * 100).round(2)
    sec = sec.sort_values("Total_Rs", ascending=False).reset_index(drop=True)
    return sec
