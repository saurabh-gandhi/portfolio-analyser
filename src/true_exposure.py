"""
Look-through logic: map every portfolio asset to its true economic exposure.
Handles EPF, PPF, NPS, LIC, REITs, Gold, Cash, Arbitrage funds.
"""
import pandas as pd
from typing import Optional


def compute_true_exposure(
    portfolio_df: pd.DataFrame,
    config: dict,
    mf_etf_holdings: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Map every row in portfolio_df to (possibly multiple) true asset class rows.

    Returns a DataFrame with columns:
        Asset, Present Value, True Asset Class, Allocation Pct, Rs Exposure
    """
    rows = []
    total = portfolio_df['PresentValue'].sum()

    arb_funds = {f.lower() for f in config.get('arbitrage_funds', [])}
    nps_cfg   = config.get('nps_scheme', {})
    epf_cfg   = config.get('epf_allocation', {})
    lic_cfg   = config.get('lic_treatment', {})
    reit_eq   = config.get('reit_equity_pct', 80)
    reit_debt = config.get('reit_debt_pct', 20)

    def add(name, pv, asset_class, pct):
        rows.append({
            'Asset': name,
            'Present Value': pv,
            'True Asset Class': asset_class,
            'Allocation Pct': pct,
            'Rs Exposure': round(pv * pct / 100, 0),
        })

    for _, row in portfolio_df.iterrows():
        name  = row['AssetName']
        pv    = row['PresentValue']
        cls   = row['InstrumentClass']
        nlo   = name.lower()

        if cls == 'epf':
            add(name, pv, 'Indian Equity',           epf_cfg.get('equity_pct', 15))
            add(name, pv, 'Indian Govt Bonds',        epf_cfg.get('govt_bond_pct', 55))
            add(name, pv, 'Indian Corp Debt / CDs',   epf_cfg.get('corp_debt_pct', 30))

        elif cls == 'ppf':
            add(name, pv, 'Indian Govt Bonds', 100.0)

        elif cls == 'nps':
            add(name, pv, 'Indian Equity',          nps_cfg.get('equity_pct', 75))
            add(name, pv, 'Indian Govt Bonds',       nps_cfg.get('govt_bond_pct', 15))
            add(name, pv, 'Indian Corp Debt / CDs',  nps_cfg.get('corp_debt_pct', 10))

        elif cls == 'lic':
            label = lic_cfg.get('asset_class', 'Debt — Insurance/LIC')
            yr    = lic_cfg.get('maturity_year', 2030)
            add(name, pv, f'{label} (Maturing {yr})', 100.0)

        elif cls == 'reit':
            add(name, pv, 'Commercial Real Estate',  reit_eq)
            add(name, pv, 'Indian Corp Debt / CDs',  reit_debt)

        elif cls == 'sgb':
            add(name, pv, 'Gold', 100.0)

        elif cls == 'gold_etf':
            add(name, pv, 'Gold', 100.0)

        elif cls == 'gold_physical':
            add(name, pv, 'Gold', 100.0)

        elif cls == 'esops':
            add(name, pv, 'Indian Private Equity (Unlisted)', 100.0)

        elif cls == 'cash':
            add(name, pv, 'Cash & Equivalents', 100.0)

        elif cls == 'bond':
            add(name, pv, 'Indian Corp Debt / CDs', 100.0)

        elif cls == 'stock':
            # Determine geography from name
            us_kw = config.get('us_equity_keywords', [])
            if any(k in nlo for k in us_kw) or row.get('CategoryNorm','') == 'international':
                add(name, pv, 'US/Intl Equity', 100.0)
            else:
                add(name, pv, 'Indian Equity', 100.0)

        elif cls in ('mf', 'etf'):
            # Arbitrage fund → cash equivalent
            if any(arb in nlo for arb in arb_funds):
                add(name, pv, 'Cash & Equivalents (Arbitrage)', 100.0)
                continue

            # Look-through using fetched holdings
            if mf_etf_holdings is not None and len(mf_etf_holdings) > 0:
                fund_h = mf_etf_holdings[mf_etf_holdings['Fund'] == name]
                if len(fund_h) > 0:
                    eq_pct  = fund_h['% to NAV'].sum()
                    cash_pct = max(100 - eq_pct, 0)

                    # Determine equity geography
                    us_kw = config.get('us_equity_keywords', [])
                    if any(k in nlo for k in us_kw):
                        add(name, pv, 'US/Intl Equity', eq_pct)
                    else:
                        add(name, pv, 'Indian Equity', eq_pct)

                    if cash_pct > 0.1:
                        add(name, pv, 'Cash & Equivalents', cash_pct)
                    continue

            # Fallback: use category from CSV
            cat = row.get('CategoryNorm', '')
            if 'international' in cat or 'us' in cat or any(k in nlo for k in config.get('us_equity_keywords', [])):
                add(name, pv, 'US/Intl Equity', 100.0)
            elif 'debt' in cat:
                add(name, pv, 'Indian Corp Debt / CDs', 100.0)
            else:
                add(name, pv, 'Indian Equity', 100.0)

        else:
            add(name, pv, 'Other / Unclassified', 100.0)

    df = pd.DataFrame(rows)

    # Roll-up by asset class
    rollup = df.groupby('True Asset Class')['Rs Exposure'].sum().reset_index()
    rollup.columns = ['True Asset Class', 'Rs Exposure']
    rollup['Pct of Total'] = rollup['Rs Exposure'] / total * 100
    rollup = rollup.sort_values('Rs Exposure', ascending=False).reset_index(drop=True)

    return df, rollup
