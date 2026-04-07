"""
Sub-class breakdown: Large/Mid/Small cap, Debt duration, Gold form, Cash type.
"""
import pandas as pd
from .utils import bar_chart


def classify_market_cap(fund_name: str, instrument_class: str, config: dict) -> dict:
    """
    Return market cap split for an equity instrument.
    E.g. {'large': 60, 'mid': 25, 'small': 15}
    """
    nlo = fund_name.lower()
    cap_map = config.get('index_market_cap', {})
    overrides = config.get('stock_market_cap_overrides', {})
    active_defaults = config.get('active_fund_defaults', {})
    lm_split = config.get('largemidcap_split', {'large_pct': 40, 'mid_pct': 60})

    # Direct stock override
    for ticker, cap in overrides.items():
        if ticker.lower() in nlo:
            return {cap: 100}

    # Index fund keyword matching
    for keyword, cap in cap_map.items():
        if keyword.lower() in nlo:
            if cap == 'mixed':
                return {'large': lm_split['large_pct'], 'mid': lm_split['mid_pct']}
            return {cap: 100}

    # US equity — all large/mega cap
    us_kw = config.get('us_equity_keywords', [])
    if any(k in nlo for k in us_kw):
        return {'large_us': 100}

    # Active fund heuristics
    if 'small cap' in nlo or 'smallcap' in nlo:
        d = active_defaults.get('small_cap', {'large': 5, 'mid': 10, 'small': 85})
    elif 'large and mid' in nlo or 'large & mid' in nlo or 'largemidcap' in nlo:
        d = active_defaults.get('large_midcap', {'large': 50, 'mid': 50})
    elif 'mid cap' in nlo or 'midcap' in nlo:
        d = {'mid': 100}
    elif 'large cap' in nlo or 'largecap' in nlo:
        d = active_defaults.get('large_cap', {'large': 100})
    elif 'flexi' in nlo or 'multi cap' in nlo or 'multicap' in nlo:
        d = active_defaults.get('flexi_cap', {'large': 60, 'mid': 25, 'small': 15})
    elif 'elss' in nlo:
        d = active_defaults.get('elss', {'large': 75, 'mid': 20, 'small': 5})
    else:
        d = {'large': 80, 'mid': 15, 'small': 5}   # generic fallback

    return d


def build_sub_class_breakdown(
    portfolio_df: pd.DataFrame,
    true_exposure_df: pd.DataFrame,
    config: dict,
    total_portfolio: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build granular sub-class exposure DataFrame.
    Returns (sub_class_rows_df, sub_class_rollup_df).
    """
    rows = []
    arb_funds = {f.lower() for f in config.get('arbitrage_funds', [])}
    reit_eq   = config.get('reit_equity_pct', 80)
    reit_debt = config.get('reit_debt_pct', 20)
    lic_cfg   = config.get('lic_treatment', {})
    nps_cfg   = config.get('nps_scheme', {})
    epf_cfg   = config.get('epf_allocation', {})
    lm_split  = config.get('largemidcap_split', {'large_pct': 40, 'mid_pct': 60})

    def add(instr, pv, sub_class, pct, note=''):
        rows.append({
            'Instrument': instr,
            'Present Value': pv,
            'Sub Class': sub_class,
            'Pct': pct,
            'Rs Exposure': round(pv * pct / 100, 0),
            'Note': note,
        })

    for _, row in portfolio_df.iterrows():
        name = row['AssetName']
        pv   = row['PresentValue']
        cls  = row['InstrumentClass']
        nlo  = name.lower()

        # ── CASH ──────────────────────────────────────────────────────────────
        if cls == 'cash':
            if 'rental' in nlo or 'deposit' in nlo:
                sub = 'Cash — Rental Deposit / Receivable'
            elif any(k in nlo for k in ['bank', 'savings', 'axis', 'hdfc', 'kotak']):
                sub = 'Cash — Bank / Savings Account'
            else:
                sub = 'Cash — Bank / Savings Account'
            add(name, pv, sub, 100.0)

        # ── GOLD ──────────────────────────────────────────────────────────────
        elif cls == 'sgb':
            add(name, pv, 'Gold — Sovereign Gold Bonds (Paper)', 100.0)
        elif cls == 'gold_etf':
            add(name, pv, 'Gold — ETF (Paper)', 100.0)
        elif cls == 'gold_physical':
            add(name, pv, 'Gold — Physical', 100.0)

        # ── PPF ───────────────────────────────────────────────────────────────
        elif cls == 'ppf':
            add(name, pv, 'Debt — Govt Bonds, Long Term (>5yr)', 100.0, 'PPF 15yr lock-in')

        # ── EPF ───────────────────────────────────────────────────────────────
        elif cls == 'epf':
            add(name, pv, 'Indian Equity — Large Cap',
                epf_cfg.get('equity_pct', 15), 'EPF equity slice (Nifty/Sensex ETFs)')
            add(name, pv, 'Debt — Govt Bonds, Long Term (>5yr)',
                epf_cfg.get('govt_bond_pct', 55), 'EPF G-Secs/SDLs')
            add(name, pv, 'Debt — Corp/Other, Long Term (3-10yr)',
                epf_cfg.get('corp_debt_pct', 30), 'EPF corporate bonds')

        # ── NPS ───────────────────────────────────────────────────────────────
        elif cls == 'nps':
            add(name, pv, 'Indian Equity — Large Cap',
                nps_cfg.get('equity_pct', 75), 'NPS equity (large-cap index)')
            add(name, pv, 'Debt — Govt Bonds, Long Term (>5yr)',
                nps_cfg.get('govt_bond_pct', 15), 'NPS G-Secs')
            add(name, pv, 'Debt — Corp/Other, Long Term (3-10yr)',
                nps_cfg.get('corp_debt_pct', 10), 'NPS corporate bonds')

        # ── LIC ───────────────────────────────────────────────────────────────
        elif cls == 'lic':
            yr  = lic_cfg.get('maturity_year', 2030)
            add(name, pv, f'Debt — LIC / Insurance, Long Term (matures {yr})',
                100.0, f'Illiquid debt wrapper maturing ~{yr}')

        # ── REIT ──────────────────────────────────────────────────────────────
        elif cls == 'reit':
            add(name, pv, 'Commercial Real Estate', reit_eq,
                'Grade A office / commercial REIT')
            add(name, pv, 'Debt — Corp/Other, Long Term (3-10yr)', reit_debt,
                'Embedded debt in REIT structure')

        # ── ESOPS ─────────────────────────────────────────────────────────────
        elif cls == 'esops':
            add(name, pv, 'Indian Equity — Unlisted / Private Equity', 100.0,
                'Unlisted equity — no public market')

        # ── BOND ──────────────────────────────────────────────────────────────
        elif cls == 'bond':
            add(name, pv, 'Debt — Corp/Other, Short Term (<3yr)', 100.0)

        # ── STOCK ─────────────────────────────────────────────────────────────
        elif cls == 'stock':
            us_kw = config.get('us_equity_keywords', [])
            if any(k in nlo for k in us_kw) or row.get('CategoryNorm','') == 'international':
                add(name, pv, 'US / Intl Equity — Large / Mega Cap', 100.0)
            else:
                cap = classify_market_cap(name, cls, config)
                for cap_type, pct in cap.items():
                    if pct <= 0:
                        continue
                    sub = {
                        'large': 'Indian Equity — Large Cap',
                        'mid':   'Indian Equity — Mid Cap',
                        'small': 'Indian Equity — Small Cap',
                    }.get(cap_type, 'Indian Equity — Large Cap')
                    add(name, pv, sub, pct)

        # ── MF / ETF ──────────────────────────────────────────────────────────
        elif cls in ('mf', 'etf'):
            if any(arb in nlo for arb in arb_funds):
                add(name, pv, 'Cash — Arbitrage Fund (Hedged, ~7-8% p.a.)', 100.0,
                    'Net equity direction ≈ 0. T+1 liquid.')
                continue

            us_kw = config.get('us_equity_keywords', [])
            is_us = any(k in nlo for k in us_kw) or row.get('CategoryNorm','') == 'international'

            if is_us:
                # FOF holding Nasdaq 100 = large/mega cap
                add(name, pv, 'US / Intl Equity — Large / Mega Cap', 99.9)
                add(name, pv, 'Cash & Equivalents — Fund Buffer', 0.1)
            else:
                # Indian equity fund — split by market cap
                total_eq_pct = 99.0   # default — overridden by API data if available
                cap = classify_market_cap(name, cls, config)

                # Check if it sums to ~100, else scale to total_eq_pct
                cap_total = sum(cap.values())
                cash_pct  = max(100 - total_eq_pct, 0)

                for cap_type, raw_pct in cap.items():
                    scaled = raw_pct / cap_total * total_eq_pct
                    sub = {
                        'large':    'Indian Equity — Large Cap',
                        'mid':      'Indian Equity — Mid Cap',
                        'small':    'Indian Equity — Small Cap',
                        'large_us': 'US / Intl Equity — Large / Mega Cap',
                    }.get(cap_type, 'Indian Equity — Large Cap')
                    add(name, pv, sub, round(scaled, 4))

                if cash_pct > 0.05:
                    add(name, pv, 'Cash & Equivalents — Fund Buffer', round(cash_pct, 4))

        else:
            add(name, pv, 'Other / Unclassified', 100.0)

    df = pd.DataFrame(rows)

    # Roll-up
    rollup = df.groupby('Sub Class')['Rs Exposure'].sum().reset_index()
    rollup.columns = ['Sub Class', 'Rs Exposure']
    rollup['Pct of Total'] = rollup['Rs Exposure'] / total_portfolio * 100
    rollup = rollup.sort_values('Rs Exposure', ascending=False).reset_index(drop=True)

    return df, rollup
