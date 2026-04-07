"""
exposure_engine.py
Computes the true economic exposure for every asset in the portfolio.
Applies look-through rules: MFs/ETFs → constituent stocks,
EPF/PPF/NPS/LIC → debt/equity splits, direct stocks → single asset, etc.
"""

import yaml
import re
from pathlib import Path
from dataclasses import dataclass, field

from .instrument_registry import InstrumentProfile, InstrumentType
from .holdings_fetcher import FundData


CONFIG_DIR = Path(__file__).parent.parent / "config"


# ── True economic asset classes ────────────────────────────────────────────────
class AssetClass:
    INDIAN_EQUITY_LARGE   = "Indian Equity — Large Cap"
    INDIAN_EQUITY_MID     = "Indian Equity — Mid Cap"
    INDIAN_EQUITY_SMALL   = "Indian Equity — Small Cap"
    INDIAN_EQUITY_UNLISTED= "Indian Equity — Unlisted / Private"
    US_EQUITY_LARGE       = "US/Intl Equity — Large/Mega Cap"
    COMMERCIAL_RE         = "Commercial Real Estate"
    GOVT_BONDS_LT         = "Indian Govt Bonds — Long Term"
    CORP_DEBT_LT_EPF      = "Indian Corp Debt — Long Term (EPF)"
    CORP_DEBT_LT_NPS      = "Indian Corp Debt — Long Term (NPS)"
    CORP_DEBT_LT_REIT     = "Indian Corp Debt — Long Term (REIT)"
    CORP_DEBT_ST_CDS      = "Indian Corp Debt — Short Term (CDs/CPs)"
    CORP_DEBT_ST_BONDS    = "Indian Corp Debt — Short Term (Bonds)"
    DEBT_LIC              = "Debt — Insurance/LIC (Long Term, ~2030)"
    GOLD_SGB              = "Gold — Sovereign Gold Bonds (Paper)"
    GOLD_PHYSICAL         = "Gold — Physical"
    GOLD_ETF              = "Gold — ETF (Paper)"
    CASH_ARBITRAGE        = "Cash & Equivalents (Arbitrage)"
    CASH_BANK             = "Cash — Bank / Savings Account"
    CASH_RENTAL           = "Cash — Rental Deposit / Receivable"
    CASH_BUFFER           = "Cash & Equivalents"


@dataclass
class ExposureRow:
    asset_name: str
    present_value: float
    true_asset_class: str
    allocation_pct: float    # % of this instrument going to this class
    rs_exposure: float       # ₹ amount
    notes: str = ""


def _load_config() -> dict:
    path = CONFIG_DIR / "asset_class_map.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_overrides() -> dict:
    path = CONFIG_DIR / "instrument_overrides.yaml"
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
            return {k.lower(): v for k, v in data.get("instruments", {}).items()}
    return {}


def _splits_to_rows(asset_name: str, present_value: float,
                    splits: dict, notes: str = "") -> list[ExposureRow]:
    rows = []
    for ac, pct in splits.items():
        if pct <= 0:
            continue
        rows.append(ExposureRow(
            asset_name=asset_name,
            present_value=present_value,
            true_asset_class=ac,
            allocation_pct=pct,
            rs_exposure=round(present_value * pct / 100, 2),
            notes=notes,
        ))
    return rows


def compute_exposure(profile: InstrumentProfile,
                     fund_data: FundData | None = None) -> list[ExposureRow]:
    """
    Compute true economic exposure rows for a single instrument.
    Returns list of ExposureRow (one per asset class split).
    """
    name = profile.asset_name
    pv = profile.present_value
    itype = profile.instrument_type
    cfg = profile.config_override
    overrides = _load_overrides()
    config = _load_config()

    # ── SGB ──────────────────────────────────────────────────────────────────
    if itype == InstrumentType.SGB:
        return _splits_to_rows(name, pv, {AssetClass.GOLD_SGB: 100}, "Sovereign Gold Bond")

    # ── Physical gold ─────────────────────────────────────────────────────────
    if itype == InstrumentType.GOLD_PHYSICAL:
        return _splits_to_rows(name, pv, {AssetClass.GOLD_PHYSICAL: 100}, "Physical gold")

    # ── Gold ETF ──────────────────────────────────────────────────────────────
    if itype == InstrumentType.GOLD_ETF:
        return _splits_to_rows(name, pv, {AssetClass.GOLD_ETF: 100}, "Gold ETF")

    # ── REIT ─────────────────────────────────────────────────────────────────
    if itype == InstrumentType.REIT:
        return _splits_to_rows(name, pv,
            {AssetClass.COMMERCIAL_RE: 80, AssetClass.CORP_DEBT_LT_REIT: 20},
            "REIT: 80% commercial RE / 20% embedded debt")

    # ── Direct Indian stock ───────────────────────────────────────────────────
    if itype == InstrumentType.DIRECT_STOCK_IN:
        # Market cap will be determined later by subclass_engine
        return _splits_to_rows(name, pv,
            {AssetClass.INDIAN_EQUITY_LARGE: 100},   # default; subclass_engine refines
            "Direct Indian stock — market cap classified separately")

    # ── Direct US stock ───────────────────────────────────────────────────────
    if itype == InstrumentType.DIRECT_STOCK_US:
        return _splits_to_rows(name, pv, {AssetClass.US_EQUITY_LARGE: 100}, "US listed stock")

    # ── US ETF ────────────────────────────────────────────────────────────────
    if itype == InstrumentType.US_ETF:
        # All US ETFs in scope are Nasdaq 100 / S&P 500 → large cap
        return _splits_to_rows(name, pv, {AssetClass.US_EQUITY_LARGE: 100}, "US ETF → large cap")

    # ── ESOP / Unlisted ───────────────────────────────────────────────────────
    if itype == InstrumentType.ESOP:
        return _splits_to_rows(name, pv,
            {AssetClass.INDIAN_EQUITY_UNLISTED: 100}, "Unlisted / ESOPs")

    # ── PPF ───────────────────────────────────────────────────────────────────
    if itype == InstrumentType.PPF:
        return _splits_to_rows(name, pv,
            {AssetClass.GOVT_BONDS_LT: 100}, "PPF: 100% sovereign bonds")

    # ── EPF ───────────────────────────────────────────────────────────────────
    if itype == InstrumentType.EPF:
        defaults = config.get("defaults", {}).get("epf", {})
        splits = defaults if defaults else {
            AssetClass.INDIAN_EQUITY_LARGE: 15,
            AssetClass.GOVT_BONDS_LT: 55,
            AssetClass.CORP_DEBT_LT_EPF: 30,
        }
        return _splits_to_rows(name, pv, splits, "EPF: EPFO mandate allocation")

    # ── NPS ───────────────────────────────────────────────────────────────────
    if itype == InstrumentType.NPS:
        scheme = cfg.get("scheme", "LC75").upper()
        nps_map = {
            "LC75": {AssetClass.INDIAN_EQUITY_LARGE: 75, AssetClass.GOVT_BONDS_LT: 15, AssetClass.CORP_DEBT_LT_NPS: 10},
            "LC50": {AssetClass.INDIAN_EQUITY_LARGE: 50, AssetClass.GOVT_BONDS_LT: 30, AssetClass.CORP_DEBT_LT_NPS: 20},
            "LC25": {AssetClass.INDIAN_EQUITY_LARGE: 25, AssetClass.GOVT_BONDS_LT: 45, AssetClass.CORP_DEBT_LT_NPS: 30},
        }
        splits = nps_map.get(scheme, nps_map["LC75"])
        return _splits_to_rows(name, pv, splits, f"NPS {scheme} scheme")

    # ── LIC ───────────────────────────────────────────────────────────────────
    if itype == InstrumentType.LIC:
        treatment = cfg.get("treatment", "debt_long_term")
        maturity = cfg.get("maturity_year", "")
        label = AssetClass.DEBT_LIC
        if maturity:
            label = f"Debt — Insurance/LIC (Long Term, ~{maturity})"
        return _splits_to_rows(name, pv, {label: 100},
            f"LIC: treated as {treatment}, matures ~{maturity}")

    # ── Bank / Cash ───────────────────────────────────────────────────────────
    if itype == InstrumentType.BANK_ACCOUNT:
        return _splits_to_rows(name, pv, {AssetClass.CASH_BANK: 100}, "Bank / savings account")

    if itype == InstrumentType.RENTAL:
        return _splits_to_rows(name, pv, {AssetClass.CASH_RENTAL: 100}, "Rental deposit/receivable")

    # ── Generic debt ─────────────────────────────────────────────────────────
    if itype == InstrumentType.DEBT_BOND:
        duration = cfg.get("duration", "short_term")
        ac = AssetClass.CORP_DEBT_ST_BONDS if duration == "short_term" else "Indian Corp Debt — Long Term (Bonds)"
        return _splits_to_rows(name, pv, {ac: 100}, f"Debt bond: {duration}")

    # ── Arbitrage fund ────────────────────────────────────────────────────────
    if itype == InstrumentType.ARBITRAGE_MF:
        return _splits_to_rows(name, pv, {AssetClass.CASH_ARBITRAGE: 100},
            "Arbitrage fund: hedged, net equity ≈ 0")

    # ── Indian MF / ETF (from mfdata.in) ─────────────────────────────────────
    if itype in (InstrumentType.INDIAN_MF, InstrumentType.INDIAN_ETF):
        if fund_data and not fund_data.error:
            eq_pct = sum(h.weight_pct for h in fund_data.equity_holdings)
            cash_pct = sum(h.weight_pct for h in fund_data.cash_holdings)
            residual = max(100 - eq_pct - cash_pct, 0)

            rows = []
            # Equity slice — asset class refinement done by subclass_engine
            if eq_pct > 0:
                rows.append(ExposureRow(
                    asset_name=name, present_value=pv,
                    true_asset_class="Indian Equity (MF/ETF — to be sub-classified)",
                    allocation_pct=eq_pct,
                    rs_exposure=round(pv * eq_pct / 100, 2),
                    notes=f"Equity from {fund_data.month}",
                ))
            if cash_pct > 0 or residual > 0:
                rows.append(ExposureRow(
                    asset_name=name, present_value=pv,
                    true_asset_class=AssetClass.CASH_BUFFER,
                    allocation_pct=cash_pct + residual,
                    rs_exposure=round(pv * (cash_pct + residual) / 100, 2),
                    notes="Cash sleeve (TREPS / CDs / net receivables)",
                ))
            return rows
        else:
            err = fund_data.error if fund_data else "No data fetched"
            return _splits_to_rows(name, pv,
                {"Indian Equity (MF/ETF — unknown)": 100},
                f"⚠️ Holdings not fetched: {err}")

    # ── Unknown ───────────────────────────────────────────────────────────────
    return [ExposureRow(
        asset_name=name, present_value=pv,
        true_asset_class="Unknown — needs configuration",
        allocation_pct=100,
        rs_exposure=pv,
        notes=f"⚠️ Unclassified: add to instrument_overrides.yaml",
    )]


def compute_all_exposures(profiles: list[InstrumentProfile],
                          holdings_map: dict) -> list[ExposureRow]:
    """Compute exposure rows for the full portfolio."""
    all_rows = []
    for profile in profiles:
        fund_data = holdings_map.get(profile.asset_name)
        rows = compute_exposure(profile, fund_data)
        all_rows.extend(rows)

    total = sum(r.rs_exposure for r in all_rows)
    print(f"[exposure_engine] Total exposure computed: ₹{total:,.0f} ({len(all_rows)} rows)")
    return all_rows
