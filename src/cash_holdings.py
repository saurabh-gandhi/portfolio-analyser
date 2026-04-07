"""Fetch cash / debt / TREPS holdings per fund from mfdata.in."""
import requests
import time
import pandas as pd
from .mf_holdings import _get, get_family_id, _HEADERS

_BENCHMARK_KEYWORDS = ['TR INR', 'Total Return', 'Nifty ', 'Sensex', 'BSE ', ' Index ']
_JUNK_SUFFIXES = ['-10.', '-11.', '-12.', '-1.5', '0.15', '28.47', '50.76']

_HOLDING_TYPE_LABELS = {
    'CA': 'TREPS / Collateral',
    'CB': 'TREPS / Collateral',
    'CD': 'Certificate of Deposit',
    'CP': 'Commercial Paper',
    'TB': 'Treasury Bills',
    'GB': 'Government Securities',
    'FO': 'Liquid Fund Units',
    'C':  'Cash',
    'CQ': 'Cash (Futures Margin)',
    'BN': 'Bonds',
    'DG': None,   # futures — skip
}


def _is_junk(name: str) -> bool:
    if not isinstance(name, str):
        return True
    for kw in _BENCHMARK_KEYWORDS + _JUNK_SUFFIXES:
        if kw.upper() in name.upper():
            return True
    try:
        float(name.replace(',', '').strip())
        return True
    except ValueError:
        pass
    return False


def fetch_fund_cash(family_id: int, fund_name: str, fund_value: float,
                    month: str = 'unknown') -> list[dict]:
    """Return cash/debt holding rows for a single fund."""
    from .mf_holdings import _get
    data = _get(f"https://mfdata.in/api/v1/families/{family_id}/holdings")
    d = data.get('data', {})

    rows = []
    eq_held = sum(h.get('weight_pct', 0) or 0 for h in d.get('equity_holdings', []) or [])
    tracked_cash_pct = 0

    for h in d.get('other_holdings', []) or []:
        htype = h.get('holding_type', '')
        label = _HOLDING_TYPE_LABELS.get(htype)
        if label is None:
            continue
        wpct = h.get('weight_pct', 0) or 0
        if wpct <= 0:
            continue
        name = h.get('name', '') or label
        if _is_junk(name):
            continue
        tracked_cash_pct += wpct
        rows.append({
            'Instrument': fund_name,
            'Item': name,
            'Category': label,
            '% to NAV': round(wpct, 4),
            'Weighted ₹ Exposure': round((wpct / 100) * fund_value, 2),
            'Instrument Value (₹)': fund_value,
            'Data As Of': month,
        })

    for h in d.get('debt_holdings', []) or []:
        wpct = h.get('weight_pct', 0) or 0
        if wpct <= 0:
            continue
        name = h.get('name', '') or 'Debt Instrument'
        if _is_junk(name) or not name or name in ('-', 'nan'):
            continue
        htype = h.get('holding_type', 'BN') or 'BN'
        label = _HOLDING_TYPE_LABELS.get(htype, 'Debt / Bonds')
        if label is None:
            continue
        rating = h.get('credit_rating', '') or ''
        display = f"{name} ({rating})" if rating else name
        tracked_cash_pct += wpct
        rows.append({
            'Instrument': fund_name,
            'Item': display,
            'Category': label,
            '% to NAV': round(wpct, 4),
            'Weighted ₹ Exposure': round((wpct / 100) * fund_value, 2),
            'Instrument Value (₹)': fund_value,
            'Data As Of': month,
        })

    # Add residual (100 - equity - tracked_cash)
    residual = max(100 - eq_held - tracked_cash_pct, 0)
    if residual > 0.1:
        rows.append({
            'Instrument': fund_name,
            'Item': f'Cash / TREPS / Net Receivables',
            'Category': 'Cash & Receivables',
            '% to NAV': round(residual, 4),
            'Weighted ₹ Exposure': round((residual / 100) * fund_value, 2),
            'Instrument Value (₹)': fund_value,
            'Data As Of': f'{month} (residual)',
        })

    return rows


def fetch_all_cash_holdings(
    portfolio_df: pd.DataFrame,
    config: dict,
    verbose: bool = True,
) -> pd.DataFrame:
    """Fetch cash/debt holdings for all MFs and ETFs in the portfolio."""
    from rich.console import Console
    console = Console()
    arb_funds = {f.lower() for f in config.get('arbitrage_funds', [])}

    all_rows = []
    seen_family_ids: dict[int, list] = {}

    mf_etf = portfolio_df[portfolio_df['InstrumentClass'].isin(['mf', 'etf'])].copy()

    for _, row in mf_etf.iterrows():
        fund_name = row['AssetName']
        fund_value = row['PresentValue']
        name_lower = fund_name.lower()

        try:
            family_id = get_family_id(fund_name)
            if family_id is None:
                continue

            # Reuse fetched data for ETFs sharing the same family (e.g. MON100 & QQQ)
            if family_id in seen_family_ids:
                base_rows = seen_family_ids[family_id]
                for r in base_rows:
                    new_r = r.copy()
                    new_r['Instrument'] = fund_name
                    new_r['Instrument Value (₹)'] = fund_value
                    new_r['Weighted ₹ Exposure'] = round(
                        (r['% to NAV'] / 100) * fund_value, 2)
                    all_rows.append(new_r)
                continue

            from .mf_holdings import _get
            data = _get(f"https://mfdata.in/api/v1/families/{family_id}/holdings")
            month = data.get('data', {}).get('month', 'unknown')

            rows = fetch_fund_cash(family_id, fund_name, fund_value, month)
            seen_family_ids[family_id] = rows
            all_rows.extend(rows)
            time.sleep(0.25)

        except Exception as e:
            if verbose:
                console.print(f"  [yellow]⚠ Cash fetch failed for {fund_name}: {e}[/yellow]")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
