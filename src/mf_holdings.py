"""Fetch mutual fund and ETF constituent holdings from mfdata.in and AMFI."""
import time
import requests
import pandas as pd
from typing import Optional
from .utils import normalise_stock_name

_BASE = "https://mfdata.in/api/v1"
_AMFI_NAV = "https://www.amfiindia.com/spages/NAVAll.txt"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1)
    return {}


def search_fund(query: str) -> list[dict]:
    """Search mfdata.in for a fund by name."""
    import urllib.parse
    data = _get(f"{_BASE}/search?q={urllib.parse.quote(query)}")
    return data.get('data', [])


def get_family_id(fund_name: str) -> Optional[int]:
    """Find the mfdata.in family_id for a fund. Returns None if not found."""
    results = search_fund(fund_name)
    for item in results:
        name_lower = item.get('name', '').lower()
        if 'growth' in name_lower and item.get('family_id'):
            return item['family_id']
    # Fallback: return first result with a family_id
    for item in results:
        if item.get('family_id'):
            return item['family_id']
    return None


def fetch_fund_holdings(family_id: int, fund_name: str, fund_value: float) -> dict:
    """
    Fetch full holdings for a fund family from mfdata.in.
    Returns dict with keys: equity_holdings, cash_pct, month, other_holdings
    """
    data = _get(f"{_BASE}/families/{family_id}/holdings")
    d = data.get('data', {})

    equity_holdings = []
    for h in d.get('equity_holdings', []) or []:
        wpct = h.get('weight_pct', 0) or 0
        if wpct <= 0:
            continue
        equity_holdings.append({
            'Fund': fund_name,
            'Stock Name': h.get('stock_name', ''),
            'ISIN': h.get('isin', '') or '',
            'Industry': h.get('sector', '') or '',
            '% to NAV': wpct,
            'Fund Value (₹)': fund_value,
            'Weighted ₹ Exposure': round((wpct / 100) * fund_value, 2),
        })

    eq_pct = min(d.get('equity_pct', 100) or 100, 100)
    eq_held = sum(h.get('weight_pct', 0) or 0 for h in d.get('equity_holdings', []) or [])

    return {
        'equity_holdings': equity_holdings,
        'equity_pct': eq_pct,
        'equity_held_pct': eq_held,
        'cash_pct': max(100 - eq_held, 0),
        'month': d.get('month', 'unknown'),
        'other_holdings': d.get('other_holdings', []) or [],
        'debt_holdings': d.get('debt_holdings', []) or [],
    }


def fetch_ppfas_xls(xls_path: str) -> dict[str, list[dict]]:
    """
    Parse PPFAS monthly portfolio XLS.
    Returns dict keyed by sheet name -> list of holding dicts.
    Known sheets: PPFCF, PPAF, PPTSF, PPCHF, PPLF
    """
    import xlrd
    wb = xlrd.open_workbook(xls_path)
    result = {}

    for sheet_name in wb.sheet_names():
        df = pd.read_excel(xls_path, sheet_name=sheet_name, engine='xlrd', header=None)
        holdings = []
        in_equity = False

        for _, row in df.iterrows():
            name = str(row[1]).strip() if pd.notna(row[1]) else ''
            col0 = str(row[0]).strip() if pd.notna(row[0]) else ''

            if 'Equity & Equity related' in name:
                in_equity = True
                continue
            if in_equity and any(x in name for x in
                                 ['Debt Instruments', 'Money Market', 'Net Assets', 'Grand Total']):
                in_equity = False
                continue
            if not in_equity:
                continue
            if name in ('', 'nan') or col0 in ('', 'nan'):
                continue
            if any(x in name for x in ['Listed', 'Unlisted', 'Sub Total', 'awaiting', 'Overseas', 'Foreign']):
                continue

            try:
                qty = float(row[4]) if pd.notna(row[4]) else None
                mv  = float(row[5]) if pd.notna(row[5]) else None
                pct = float(row[6]) if pd.notna(row[6]) else None
            except (ValueError, TypeError):
                continue

            if any(v is None or v <= 0 for v in [qty, mv, pct]):
                continue

            isin     = str(row[2]).strip() if pd.notna(row[2]) else ''
            industry = str(row[3]).strip() if pd.notna(row[3]) else ''
            holdings.append({
                'Stock Name': name,
                'ISIN': isin,
                'Industry': industry,
                'Quantity': qty,
                'Market Value (Rs Lakhs)': round(mv, 2),
                '% to NAV': round(pct * 100, 4),
            })

        result[sheet_name] = holdings

    return result


def fetch_all_mf_etf_holdings(
    portfolio_df: pd.DataFrame,
    ppfas_xls_path: Optional[str],
    config: dict,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Main entry point: fetch equity holdings for all MFs and ETFs in the portfolio.
    Returns a combined DataFrame of all holdings with weighted ₹ exposure.
    """
    from rich.console import Console
    from rich.progress import track
    console = Console()

    arb_funds = {f.lower() for f in config.get('arbitrage_funds', [])}
    all_rows = []

    # Load PPFAS XLS if provided
    ppfas_data = {}
    if ppfas_xls_path:
        try:
            ppfas_data = fetch_ppfas_xls(ppfas_xls_path)
            console.print(f"[green]✓ PPFAS XLS loaded: {list(ppfas_data.keys())}[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ PPFAS XLS load failed: {e}[/yellow]")

    # PPFAS fund name → sheet name mapping
    ppfas_sheet_map = {
        'parag parikh flexi cap': 'PPFCF',
        'parag parikh arbitrage': 'PPAF',
        'parag parikh elss': 'PPTSF',
        'parag parikh conservative': 'PPCHF',
        'parag parikh liquid': 'PPLF',
        'parag parikh large cap': 'PPLCF',
    }

    mf_etf_rows = portfolio_df[portfolio_df['InstrumentClass'].isin(['mf', 'etf'])].copy()

    for _, row in track(mf_etf_rows.iterrows(), description="Fetching fund holdings...",
                        total=len(mf_etf_rows)):
        fund_name = row['AssetName']
        fund_value = row['PresentValue']
        name_lower = fund_name.lower()

        # Skip arbitrage funds — they are cash equivalents
        if any(arb in name_lower for arb in arb_funds):
            if verbose:
                console.print(f"  [yellow]↷ Skipping arbitrage fund (cash equivalent): {fund_name}[/yellow]")
            continue

        # Try PPFAS XLS first
        ppfas_sheet = None
        for key, sheet in ppfas_sheet_map.items():
            if key in name_lower:
                ppfas_sheet = sheet
                break

        if ppfas_sheet and ppfas_sheet in ppfas_data:
            holdings = ppfas_data[ppfas_sheet]
            for h in holdings:
                all_rows.append({
                    'Fund': fund_name,
                    'Stock Name': h['Stock Name'],
                    'ISIN': h['ISIN'],
                    'Industry': h['Industry'],
                    '% to NAV': h['% to NAV'],
                    'Fund Value (₹)': fund_value,
                    'Weighted ₹ Exposure': round((h['% to NAV'] / 100) * fund_value, 2),
                    'Data Source': 'PPFAS XLS',
                })
            if verbose:
                console.print(f"  [green]✓ {fund_name}: {len(holdings)} holdings (PPFAS XLS)[/green]")
            continue

        # Try mfdata.in API
        try:
            family_id = get_family_id(fund_name)
            if family_id is None:
                console.print(f"  [yellow]⚠ Could not find family_id for: {fund_name}[/yellow]")
                continue

            result = fetch_fund_holdings(family_id, fund_name, fund_value)
            for h in result['equity_holdings']:
                h['Data Source'] = f"mfdata.in ({result['month']})"
                all_rows.append(h)

            if verbose:
                console.print(f"  [green]✓ {fund_name}: {len(result['equity_holdings'])} holdings "
                              f"(mfdata.in, {result['month']})[/green]")
            time.sleep(0.3)

        except Exception as e:
            console.print(f"  [red]✗ Failed for {fund_name}: {e}[/red]")

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df['Stock Name Norm'] = df['Stock Name'].apply(normalise_stock_name)
    return df
