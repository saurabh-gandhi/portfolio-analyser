"""
subclass_engine.py
Produces the sub-class breakdown:
  - Indian Equity → Large / Mid / Small / Unlisted
  - US Equity → (all Large/Mega Cap for Nasdaq 100 focus)
  - Debt → Long Term (Govt / LIC / Corp) vs Short Term (CDs / Bonds)
  - Gold → SGBs / Physical / ETF
  - Cash → Arbitrage / Bank / Fund Buffer / Rental
"""

import yaml
import pandas as pd
from pathlib import Path

from .instrument_registry import InstrumentProfile, InstrumentType


CONFIG_DIR = Path(__file__).parent.parent / "config"


# ── Market cap classification per fund ───────────────────────────────────────
# Approximate splits; can be overridden in config
DEFAULT_MARKET_CAP_SPLITS = {
    # Format: {amfi_category_lower: {large_pct, mid_pct, small_pct}}
    "large cap":          {"large": 95, "mid": 3,  "small": 2},
    "mid cap":            {"large": 10, "mid": 80, "small": 10},
    "small cap":          {"large": 5,  "mid": 10, "small": 85},
    "flexi cap":          {"large": 55, "mid": 30, "small": 15},
    "multi cap":          {"large": 33, "mid": 33, "small": 34},
    "large & midcap":     {"large": 50, "mid": 50, "small": 0},
    "large and midcap":   {"large": 50, "mid": 50, "small": 0},
    "largemidcap":        {"large": 50, "mid": 50, "small": 0},
    "elss":               {"large": 75, "mid": 20, "small": 5},
    "nifty 50":           {"large": 100, "mid": 0,  "small": 0},
    "nifty next 50":      {"large": 100, "mid": 0,  "small": 0},
    "nifty 100":          {"large": 100, "mid": 0,  "small": 0},
    "nifty midcap 150":   {"large": 0,  "mid": 100, "small": 0},
    "nifty largemidcap 250": {"large": 40, "mid": 60, "small": 0},
    "nifty smallcap":     {"large": 0,  "mid": 10, "small": 90},
    "focused":            {"large": 70, "mid": 25, "small": 5},
    "value":              {"large": 65, "mid": 25, "small": 10},
}

# Per-instrument market cap splits (used when we know the fund well)
INSTRUMENT_MARKET_CAP = {
    # ETFs
    "NIFTYBEES":    {"large": 100, "mid": 0,  "small": 0},
    "JUNIORBEES":   {"large": 100, "mid": 0,  "small": 0},
    "MIDCAPETF":    {"large": 0,   "mid": 100, "small": 0},
    "GOLDBEES":     {},  # not equity
    "MON100":       {},  # US equity, handled separately
    "QQQ":          {},  # US equity
    # Known MF splits (approximations)
    "ZERODHA NIFTY LARGEMIDCAP 250 INDEX FUND": {"large": 40, "mid": 60, "small": 0},
    "PARAG PARIKH FLEXI CAP FUND":     {"large": 60, "mid": 30, "small": 10},  # Indian equity portion
    "BANDHAN SMALL CAP FUND":          {"large": 5,  "mid": 10, "small": 85},
    "NIPPON INDIA SMALL CAP FUND":     {"large": 5,  "mid": 10, "small": 85},
    "MIRAE ASSET ELSS TAX SAVER FUND": {"large": 75, "mid": 20, "small": 5},
    "MIRAE ASSET LARGE & MIDCAP FUND": {"large": 50, "mid": 50, "small": 0},
}

# Direct stock market cap (override via market_cap_overrides.yaml)
DIRECT_STOCK_CAP_DEFAULT = "large"  # default for any listed Indian stock


def _load_market_cap_overrides() -> dict:
    path = CONFIG_DIR / "market_cap_overrides.yaml"
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
            return {k.upper(): v for k, v in data.get("stocks", {}).items()}
    return {}


def _get_instrument_market_cap_split(instrument_name: str) -> dict:
    """Return {large, mid, small} % split for an instrument's Indian equity portion."""
    name_upper = instrument_name.upper().strip()

    # Exact match in known table
    for key, splits in INSTRUMENT_MARKET_CAP.items():
        if name_upper == key.upper():
            return splits

    # Partial match for index funds
    if "NIFTY 50" in name_upper and "NEXT" not in name_upper:
        return {"large": 100, "mid": 0, "small": 0}
    if "NIFTY NEXT 50" in name_upper:
        return {"large": 100, "mid": 0, "small": 0}
    if "MIDCAP" in name_upper and "LARGEMID" not in name_upper and "LARGE" not in name_upper:
        return {"large": 0, "mid": 100, "small": 0}
    if "LARGEMIDCAP" in name_upper or "LARGE & MID" in name_upper or "LARGE AND MID" in name_upper:
        return {"large": 40, "mid": 60, "small": 0}
    if "SMALL CAP" in name_upper or "SMALLCAP" in name_upper:
        return {"large": 5, "mid": 10, "small": 85}
    if "FLEXI CAP" in name_upper:
        return {"large": 55, "mid": 30, "small": 15}
    if "LARGE CAP" in name_upper or "LARGECAP" in name_upper:
        return {"large": 95, "mid": 3, "small": 2}
    if "ELSS" in name_upper:
        return {"large": 75, "mid": 20, "small": 5}
    if "NASDAQ" in name_upper or "NASDAQ 100" in name_upper:
        return {}  # US equity

    return {"large": 65, "mid": 25, "small": 10}  # generic active fund default


def build_subclass_breakdown(profiles: list[InstrumentProfile],
                             exposure_rows: list,
                             total_portfolio_value: float) -> dict:
    """
    Build a dictionary of sub-class buckets with ₹ exposure and %.
    Returns: {sub_class_label: {"rs": float, "pct_total": float, "sources": str}}
    """
    mc_overrides = _load_market_cap_overrides()
    buckets: dict[str, float] = {}

    def add(bucket: str, amount: float):
        buckets[bucket] = buckets.get(bucket, 0) + amount

    for profile in profiles:
        name = profile.asset_name
        pv = profile.present_value
        itype = profile.instrument_type
        cfg = profile.config_override

        # ── Indian equity — split by market cap ──────────────────────────────
        if itype in (InstrumentType.INDIAN_MF, InstrumentType.INDIAN_ETF):
            # Get the equity % from exposure rows
            eq_rs = sum(r.rs_exposure for r in exposure_rows
                        if r.asset_name == name and "equity" in r.true_asset_class.lower())
            cash_rs = pv - eq_rs

            if eq_rs > 0:
                splits = _get_instrument_market_cap_split(name)
                if splits:
                    add("Indian Equity — Large Cap",   eq_rs * splits.get("large", 0) / 100)
                    add("Indian Equity — Mid Cap",     eq_rs * splits.get("mid",   0) / 100)
                    add("Indian Equity — Small Cap",   eq_rs * splits.get("small", 0) / 100)
                else:
                    # US/overseas equity FOF
                    add("US/Intl Equity — Large/Mega Cap", eq_rs)

            if cash_rs > 0:
                add("Cash & Equivalents", cash_rs)

        elif itype == InstrumentType.DIRECT_STOCK_IN:
            cap = mc_overrides.get(name.upper(), DIRECT_STOCK_CAP_DEFAULT)
            cap_map = {
                "large_cap": "Indian Equity — Large Cap",
                "large":     "Indian Equity — Large Cap",
                "mid_cap":   "Indian Equity — Mid Cap",
                "mid":       "Indian Equity — Mid Cap",
                "small_cap": "Indian Equity — Small Cap",
                "small":     "Indian Equity — Small Cap",
                "unlisted":  "Indian Equity — Unlisted / Private",
            }
            add(cap_map.get(cap, "Indian Equity — Large Cap"), pv)

        elif itype == InstrumentType.DIRECT_STOCK_US:
            add("US/Intl Equity — Large/Mega Cap", pv)

        elif itype == InstrumentType.US_ETF:
            add("US/Intl Equity — Large/Mega Cap", pv)

        elif itype == InstrumentType.ESOP:
            add("Indian Equity — Unlisted / Private", pv)

        elif itype == InstrumentType.REIT:
            add("Commercial Real Estate", pv * 0.80)
            add("Indian Corp Debt — Long Term (REIT)", pv * 0.20)

        elif itype == InstrumentType.NPS:
            scheme = cfg.get("scheme", "LC75").upper()
            nps_splits = {
                "LC75": [(75, "Indian Equity — Large Cap"), (15, "Indian Govt Bonds — Long Term"), (10, "Indian Corp Debt — Long Term (NPS)")],
                "LC50": [(50, "Indian Equity — Large Cap"), (30, "Indian Govt Bonds — Long Term"), (20, "Indian Corp Debt — Long Term (NPS)")],
                "LC25": [(25, "Indian Equity — Large Cap"), (45, "Indian Govt Bonds — Long Term"), (30, "Indian Corp Debt — Long Term (NPS)")],
            }
            for pct, bucket in nps_splits.get(scheme, nps_splits["LC75"]):
                add(bucket, pv * pct / 100)

        elif itype == InstrumentType.EPF:
            add("Indian Equity — Large Cap",           pv * 0.15)
            add("Indian Govt Bonds — Long Term",       pv * 0.55)
            add("Indian Corp Debt — Long Term (EPF)",  pv * 0.30)

        elif itype == InstrumentType.PPF:
            add("Indian Govt Bonds — Long Term", pv)

        elif itype == InstrumentType.LIC:
            maturity = cfg.get("maturity_year", "")
            label = f"Debt — Insurance/LIC (Long Term, ~{maturity})" if maturity else "Debt — Insurance/LIC (Long Term)"
            add(label, pv)

        elif itype == InstrumentType.SGB:
            add("Gold — Sovereign Gold Bonds (Paper)", pv)

        elif itype == InstrumentType.GOLD_PHYSICAL:
            add("Gold — Physical", pv)

        elif itype == InstrumentType.GOLD_ETF:
            add("Gold — ETF (Paper)", pv)

        elif itype == InstrumentType.ARBITRAGE_MF:
            add("Cash & Equivalents (Arbitrage)", pv)

        elif itype == InstrumentType.BANK_ACCOUNT:
            add("Cash — Bank / Savings Account", pv)

        elif itype == InstrumentType.RENTAL:
            add("Cash — Rental Deposit / Receivable", pv)

        elif itype == InstrumentType.DEBT_BOND:
            duration = cfg.get("duration", "short_term")
            label = "Indian Corp Debt — Short Term (Bonds)" if duration == "short_term" else "Indian Corp Debt — Long Term (Bonds)"
            add(label, pv)

    # Convert to DataFrame
    rows = []
    for sub_class, rs in buckets.items():
        if rs > 0:
            rows.append({
                "Sub Class": sub_class,
                "Rs Exposure": round(rs, 0),
                "Pct of Total": round(rs / total_portfolio_value * 100, 4),
            })

    df = pd.DataFrame(rows).sort_values("Rs Exposure", ascending=False).reset_index(drop=True)
    return df
