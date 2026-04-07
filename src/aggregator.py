"""Stock-level and sector-level roll-ups from raw holdings data."""
import pandas as pd
from .utils import normalise_stock_name, best_sector


def build_stock_rollup(
    all_holdings: pd.DataFrame,
    total_equity_value: float,
    total_portfolio: float,
) -> pd.DataFrame:
    """
    Aggregate all holdings to unique stock level.
    Returns DataFrame sorted by total ₹ exposure descending.
    """
    if all_holdings.empty:
        return pd.DataFrame()

    # Normalise names
    df = all_holdings.copy()
    df['Stock Norm'] = df['Stock Name'].apply(normalise_stock_name)

    # For each stock, pick best sector across all appearances
    meta = df.groupby('Stock Norm').agg(
        Sector=('Industry', lambda x: best_sector(list(x))),
        Original_Names=('Stock Name', lambda x: ' / '.join(sorted(set(str(n) for n in x))[:3])),
    ).reset_index()

    # Aggregate financials
    agg = df.groupby('Stock Norm').agg(
        Instruments=('Fund', 'nunique'),
        Held_In=('Fund', lambda x: ' | '.join(sorted(set(x)))),
        Total_Rs=('Weighted ₹ Exposure', 'sum'),
        Max_Pct=('% to NAV', 'max'),
        Source_Types=('Data Source', lambda x: ' + '.join(sorted(set(str(s) for s in x if s)))),
    ).reset_index()

    result = agg.merge(meta, on='Stock Norm', how='left')
    result['Pct of Total Portfolio'] = result['Total_Rs'] / total_portfolio * 100
    result['Pct of Equity Pool']     = result['Total_Rs'] / total_equity_value * 100 \
                                        if total_equity_value > 0 else 0
    result = result.sort_values('Total_Rs', ascending=False).reset_index(drop=True)
    result.insert(0, 'Rank', range(1, len(result) + 1))

    result = result.rename(columns={
        'Stock Norm':   'Stock Name',
        'Total_Rs':     'Total ₹ Exposure',
        'Max_Pct':      'Max % in Any Instrument',
        'Source_Types': 'Source',
        'Held_In':      'Held In',
        'Original_Names': 'Original Names',
    })
    return result


def build_sector_rollup(
    all_holdings: pd.DataFrame,
    total_equity_value: float,
    total_portfolio: float,
) -> pd.DataFrame:
    """Aggregate holdings to sector level."""
    if all_holdings.empty:
        return pd.DataFrame()

    df = all_holdings.copy()
    df['Industry'] = df['Industry'].fillna('Unknown')
    df['Stock Norm'] = df['Stock Name'].apply(normalise_stock_name)

    rollup = df.groupby('Industry').agg(
        Stock_Count=('Stock Norm', 'nunique'),
        Total_Rs=('Weighted ₹ Exposure', 'sum'),
    ).reset_index()

    rollup['Pct of Equity Pool']     = rollup['Total_Rs'] / total_equity_value * 100 \
                                        if total_equity_value > 0 else 0
    rollup['Pct of Total Portfolio'] = rollup['Total_Rs'] / total_portfolio * 100
    rollup = rollup.sort_values('Total_Rs', ascending=False).reset_index(drop=True)
    rollup.insert(0, 'Rank', range(1, len(rollup) + 1))

    return rollup
