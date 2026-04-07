"""
holdings_fetcher.py
Fetches underlying constituent holdings for each instrument.
Primary source: mfdata.in API (free, no auth, covers all Indian MFs/ETFs).
"""

import time
import urllib.request
import urllib.parse
import json
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from .instrument_registry import InstrumentProfile, InstrumentType


BASE_URL = "https://mfdata.in/api/v1"
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
REQUEST_DELAY = 0.3  # seconds between API calls


@dataclass
class Holding:
    stock_name: str
    sector: str
    weight_pct: float        # % of fund NAV
    market_value_rs: float   # in rupees
    isin: str = ""
    holding_type: str = "equity"   # equity, debt, cash, treps, futures


@dataclass
class FundData:
    instrument_name: str
    present_value: float
    month: str
    equity_pct: float
    equity_holdings: list[Holding] = field(default_factory=list)
    cash_holdings: list[Holding] = field(default_factory=list)
    error: str = ""


# ── Junk / benchmark row detection ───────────────────────────────────────────
BENCHMARK_KEYWORDS = ["TR INR", "Total Return", " Index ", " TR ", "Nifty ", "BSE ", "Sensex"]
FUTURES_HOLDING_TYPES = {"DG"}  # derivative/futures

def _is_junk(name: str) -> bool:
    if not name or name in ["-", "nan", "0"]:
        return True
    for kw in BENCHMARK_KEYWORDS:
        if kw.upper() in name.upper():
            return True
    try:
        float(name.replace(",", "").strip())
        return True
    except ValueError:
        pass
    return False


# ── HTTP helper ───────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

def _api_get(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── AMFI name → scheme code lookup ───────────────────────────────────────────
_amfi_cache: dict[str, str] = {}

def _load_amfi_nav() -> dict[str, str]:
    """Load AMFI NAV file and return {scheme_name_lower: amfi_code}."""
    global _amfi_cache
    if _amfi_cache:
        return _amfi_cache
    try:
        req = urllib.request.Request(AMFI_NAV_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read().decode("utf-8", errors="replace")
        for line in data.splitlines():
            parts = line.split(";")
            if len(parts) >= 4:
                code = parts[0].strip()
                name = parts[3].strip().lower()
                if code.isdigit():
                    _amfi_cache[name] = code
    except Exception as e:
        print(f"[holdings_fetcher] Warning: could not load AMFI NAV: {e}")
    return _amfi_cache


def search_fund_family(fund_name: str) -> Optional[int]:
    """Search mfdata.in for a fund's family_id by name."""
    try:
        q = urllib.parse.quote(fund_name[:50])
        data = _api_get(f"{BASE_URL}/search?q={q}")
        for item in data.get("data", []):
            name_lower = item.get("name", "").lower()
            if "growth" in name_lower and item.get("family_id"):
                return int(item["family_id"])
    except Exception as e:
        print(f"[holdings_fetcher] Search failed for '{fund_name}': {e}")
    return None


def fetch_fund_holdings(family_id: int, instrument_name: str,
                        present_value: float) -> FundData:
    """Fetch equity + cash holdings for a fund family from mfdata.in."""
    try:
        time.sleep(REQUEST_DELAY)
        data = _api_get(f"{BASE_URL}/families/{family_id}/holdings")
        d = data["data"]
        month = d.get("month", "unknown")
        eq_pct = min(d.get("equity_pct", 100) or 100, 100)

        equity_holdings = []
        for h in (d.get("equity_holdings") or []):
            wpct = h.get("weight_pct", 0) or 0
            if wpct <= 0:
                continue
            mv = (wpct / 100) * present_value
            equity_holdings.append(Holding(
                stock_name=h.get("stock_name", ""),
                sector=h.get("sector", "") or "",
                weight_pct=wpct,
                market_value_rs=mv,
                isin=h.get("isin", "") or "",
                holding_type="equity",
            ))

        # Cash/debt holdings from other_holdings
        cash_holdings = []
        for h in (d.get("other_holdings") or []):
            htype = h.get("holding_type", "")
            if htype in FUTURES_HOLDING_TYPES:
                continue  # skip futures
            name = h.get("name", "") or ""
            if _is_junk(name):
                continue
            wpct = h.get("weight_pct", 0) or 0
            if wpct <= 0:
                continue
            mv = (wpct / 100) * present_value
            cash_holdings.append(Holding(
                stock_name=name,
                sector=_map_cash_type(htype),
                weight_pct=wpct,
                market_value_rs=mv,
                holding_type="cash",
            ))

        for h in (d.get("debt_holdings") or []):
            name = h.get("name", "") or ""
            if _is_junk(name):
                continue
            wpct = h.get("weight_pct", 0) or 0
            if wpct <= 0:
                continue
            htype = h.get("holding_type", "BN") or "BN"
            if htype in FUTURES_HOLDING_TYPES:
                continue
            rating = h.get("credit_rating", "") or ""
            display = f"{name} ({rating})" if rating else name
            mv = (wpct / 100) * present_value
            cash_holdings.append(Holding(
                stock_name=display,
                sector=_map_debt_type(htype),
                weight_pct=wpct,
                market_value_rs=mv,
                holding_type="debt",
            ))

        # Residual cash
        eq_sum = sum(h.weight_pct for h in equity_holdings)
        cash_sum = sum(h.weight_pct for h in cash_holdings)
        residual = max(100 - eq_sum - cash_sum, 0)
        if residual > 0.05:
            cash_holdings.append(Holding(
                stock_name="Cash / TREPS / Net Receivables",
                sector="Cash & Receivables",
                weight_pct=residual,
                market_value_rs=(residual / 100) * present_value,
                holding_type="cash",
            ))

        return FundData(
            instrument_name=instrument_name,
            present_value=present_value,
            month=month,
            equity_pct=eq_sum,
            equity_holdings=equity_holdings,
            cash_holdings=cash_holdings,
        )

    except Exception as e:
        return FundData(
            instrument_name=instrument_name,
            present_value=present_value,
            month="error",
            equity_pct=0,
            error=str(e),
        )


def _map_cash_type(htype: str) -> str:
    mapping = {
        "CA": "TREPS / Collateral", "CB": "TREPS / Collateral",
        "CD": "Certificate of Deposit", "CP": "Commercial Paper",
        "TB": "Treasury Bills", "GB": "Government Securities",
        "FO": "Liquid Fund Units", "C": "Cash",
        "CQ": "Cash (Futures Margin)",
    }
    return mapping.get(htype, "Cash & Equivalents")


def _map_debt_type(htype: str) -> str:
    mapping = {
        "CD": "Certificate of Deposit", "CP": "Commercial Paper",
        "TB": "Treasury Bills", "GB": "Government Securities",
        "BN": "Bonds / NCD", "SD": "State Development Loans",
    }
    return mapping.get(htype, "Debt / Bonds")


def fetch_all_holdings(profiles: list[InstrumentProfile],
                       ppfas_xls_path: str = None) -> dict[str, FundData]:
    """
    Fetch constituent holdings for all instruments.
    Returns dict: {asset_name: FundData}
    """
    results = {}
    mf_profiles = [p for p in profiles if p.fetch_strategy in
                   ("mfdata_api", "mfdata_api_search")]

    print(f"[holdings_fetcher] Fetching holdings for {len(mf_profiles)} MF/ETF instruments...")

    for i, profile in enumerate(mf_profiles):
        name = profile.asset_name
        pv = profile.present_value

        # Get or resolve family_id
        family_id = profile.amfi_family_id

        if family_id is None:
            print(f"  [{i+1}/{len(mf_profiles)}] Searching: {name[:50]}...")
            family_id = search_fund_family(name)
            if family_id is None:
                print(f"    ⚠️  Could not find family_id for: {name}")
                results[name] = FundData(
                    instrument_name=name, present_value=pv,
                    month="unknown", equity_pct=0,
                    error="Could not find fund on mfdata.in. Add family_id to instrument_overrides.yaml"
                )
                continue
        else:
            print(f"  [{i+1}/{len(mf_profiles)}] Fetching: {name[:50]} (family_id={family_id})...")

        fd = fetch_fund_holdings(family_id, name, pv)
        if fd.error:
            print(f"    ⚠️  Error: {fd.error}")
        else:
            print(f"    ✓  {len(fd.equity_holdings)} equity + {len(fd.cash_holdings)} cash holdings ({fd.month})")
        results[name] = fd

    # PPFAS XLS (optional manual upload)
    if ppfas_xls_path:
        ppfas_data = _parse_ppfas_xls(ppfas_xls_path, profiles)
        results.update(ppfas_data)

    return results


def _parse_ppfas_xls(xls_path: str, profiles: list[InstrumentProfile]) -> dict:
    """Parse PPFAS monthly portfolio XLS file."""
    import xlrd
    results = {}
    try:
        import pandas as pd
        wb_xlrd = xlrd.open_workbook(xls_path)
        sheets = wb_xlrd.sheet_names()

        sheet_to_fund = {
            "PPFCF": "Parag Parikh Flexi Cap Fund",
            "PPAF":  "Parag Parikh Arbitrage Fund",
            "PPTSF": "Parag Parikh ELSS Tax Saver Fund",
        }

        # Find matching profiles
        fund_pv_map = {p.asset_name: p.present_value for p in profiles}

        for sheet_name, fund_label in sheet_to_fund.items():
            if sheet_name not in sheets:
                continue
            pv = fund_pv_map.get(fund_label, 0)
            if pv == 0:
                continue

            df = pd.read_excel(xls_path, sheet_name=sheet_name, engine="xlrd", header=None)
            holdings = []
            in_equity = False
            for _, row in df.iterrows():
                name = str(row[1]).strip() if pd.notna(row[1]) else ""
                col0 = str(row[0]).strip() if pd.notna(row[0]) else ""
                if "Equity & Equity related" in name:
                    in_equity = True; continue
                if in_equity and any(x in name for x in ["Debt Instruments", "Money Market", "Net Assets"]):
                    in_equity = False; continue
                if not in_equity: continue
                if not name or name == "nan" or not col0 or col0 == "nan": continue
                if any(x in name for x in ["Listed", "Unlisted", "Sub Total", "awaiting", "Overseas"]): continue
                try:
                    mv = float(row[5]) if pd.notna(row[5]) else None
                    pct = float(row[6]) if pd.notna(row[6]) else None
                except: continue
                if mv is None or pct is None or mv <= 0: continue
                industry = str(row[3]).strip() if pd.notna(row[3]) else ""
                holdings.append(Holding(
                    stock_name=name, sector=industry,
                    weight_pct=round(pct * 100, 4),
                    market_value_rs=(pct * 100 / 100) * pv,
                    isin=str(row[2]).strip() if pd.notna(row[2]) else "",
                    holding_type="equity",
                ))

            eq_pct = sum(h.weight_pct for h in holdings)
            results[fund_label] = FundData(
                instrument_name=fund_label, present_value=pv,
                month="Feb 2026 (manual XLS)", equity_pct=eq_pct,
                equity_holdings=holdings,
            )
            print(f"  ✓  PPFAS XLS: {fund_label} — {len(holdings)} holdings")

    except Exception as e:
        print(f"[holdings_fetcher] PPFAS XLS parse error: {e}")

    return results
