#!/usr/bin/env python3
"""
Portfolio Analyser — CLI entrypoint.

Usage:
  python run.py --portfolio my_portfolio.csv
  python run.py --portfolio my_portfolio.csv --ppfas-xls PPFAS_Feb_2026.xls --output analysis.xlsx
  python run.py --portfolio data/sample/sample_portfolio.csv --verbose
"""
import argparse
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description='Indian Portfolio Analyser — bottoms-up look-through analysis'
    )
    parser.add_argument('--portfolio',   required=True, help='Path to portfolio CSV')
    parser.add_argument('--output',      default='portfolio_analysis.xlsx', help='Output Excel file path')
    parser.add_argument('--ppfas-xls',   default=None,  help='Path to PPFAS monthly portfolio XLS (optional)')
    parser.add_argument('--config',      default='config/instrument_config.yaml', help='Config file path')
    parser.add_argument('--verbose',     action='store_true', help='Verbose output')
    parser.add_argument('--no-cash',     action='store_true', help='Skip cash/debt holdings fetch (faster)')
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold blue]📊 Indian Portfolio Analyser[/bold blue]\n"
        "Bottoms-up look-through: MFs, ETFs, EPF, PPF, NPS, LIC, REITs → True Asset Allocation",
        border_style='blue'
    ))

    # ── Load config ───────────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
        console.print(f"[green]✓[/green] Config loaded: {args.config}")
    except FileNotFoundError:
        console.print(f"[red]✗ Config file not found: {args.config}[/red]")
        sys.exit(1)

    # ── Load portfolio ────────────────────────────────────────────────────────
    from src.portfolio_loader import PortfolioLoader
    try:
        loader = PortfolioLoader(args.portfolio)
        portfolio_df = loader.load()
        total = loader.total_value
        console.print(f"[green]✓[/green] Portfolio loaded: {len(portfolio_df)} instruments, "
                      f"total ₹{total:,.0f}")
    except Exception as e:
        console.print(f"[red]✗ Portfolio load failed: {e}[/red]")
        sys.exit(1)

    summary = loader.summary()
    console.print("\n[bold]Instrument breakdown:[/bold]")
    for cls, data in sorted(summary['by_class'].items()):
        console.print(f"  {cls:<20} {int(data['count']):>3} instruments   ₹{data['sum']:>12,.0f}")

    # ── Fetch MF/ETF constituent holdings ────────────────────────────────────
    console.print("\n[bold]Step 1: Fetching fund constituent holdings...[/bold]")
    from src.mf_holdings import fetch_all_mf_etf_holdings
    mf_holdings = fetch_all_mf_etf_holdings(
        portfolio_df,
        ppfas_xls_path=args.ppfas_xls,
        config=config,
        verbose=args.verbose,
    )
    console.print(f"[green]✓[/green] MF/ETF holdings: {len(mf_holdings)} rows across "
                  f"{mf_holdings['Fund'].nunique() if len(mf_holdings) > 0 else 0} funds")

    # ── Fetch cash/debt holdings ──────────────────────────────────────────────
    cash_df = None
    if not args.no_cash:
        console.print("\n[bold]Step 2: Fetching cash & debt holdings...[/bold]")
        from src.cash_holdings import fetch_all_cash_holdings
        cash_df = fetch_all_cash_holdings(portfolio_df, config, verbose=args.verbose)
        console.print(f"[green]✓[/green] Cash/debt holdings: {len(cash_df)} rows")

    # ── Build ETF direct stock holdings ──────────────────────────────────────
    console.print("\n[bold]Step 3: Building ETF and direct stock positions...[/bold]")
    from src.mf_holdings import fetch_all_mf_etf_holdings
    # Direct stocks contribute to stock roll-up as 100% of their value
    direct_rows = []
    stock_rows = portfolio_df[portfolio_df['InstrumentClass'] == 'stock']
    for _, r in stock_rows.iterrows():
        direct_rows.append({
            'Fund': r['AssetName'],
            'Stock Name': r['AssetName'],
            'ISIN': '',
            'Industry': r.get('Asset Category', ''),
            '% to NAV': 100.0,
            'Fund Value (₹)': r['PresentValue'],
            'Weighted ₹ Exposure': r['PresentValue'],
            'Data Source': 'Direct holding',
            'Stock Name Norm': r['AssetName'].upper(),
        })

    import pandas as pd
    all_holdings = pd.concat([mf_holdings, pd.DataFrame(direct_rows)], ignore_index=True)
    console.print(f"[green]✓[/green] Total holdings rows: {len(all_holdings)}")

    # ── True exposure look-through ────────────────────────────────────────────
    console.print("\n[bold]Step 4: Computing true asset class exposure...[/bold]")
    from src.true_exposure import compute_true_exposure
    exposure_df, rollup_df = compute_true_exposure(portfolio_df, config, mf_holdings)
    console.print(f"[green]✓[/green] {len(rollup_df)} true asset classes identified")
    console.print("\n[bold]True Asset Allocation:[/bold]")
    for _, r in rollup_df.iterrows():
        bar = '█' * max(1, round(r['Pct of Total'] / 3)) + '░' * (30 - max(1, round(r['Pct of Total'] / 3)))
        console.print(f"  {r['True Asset Class']:<45} {r['Pct of Total']:>5.1f}%  {bar}")

    # ── Sub-class breakdown ───────────────────────────────────────────────────
    console.print("\n[bold]Step 5: Building sub-class breakdown (Large/Mid/Small, Debt duration...)...[/bold]")
    from src.sub_class import build_sub_class_breakdown
    sub_df, sub_rollup = build_sub_class_breakdown(portfolio_df, exposure_df, config, total)
    console.print(f"[green]✓[/green] {len(sub_rollup)} sub-classes")

    # ── Stock and sector roll-ups ─────────────────────────────────────────────
    console.print("\n[bold]Step 6: Aggregating stock-level and sector roll-ups...[/bold]")
    from src.aggregator import build_stock_rollup, build_sector_rollup
    equity_pool = rollup_df[rollup_df['True Asset Class'].isin(
        ['Indian Equity', 'Indian Private Equity (Unlisted)', 'US/Intl Equity', 'Commercial Real Estate']
    )]['Rs Exposure'].sum()

    stock_rollup  = build_stock_rollup(all_holdings, equity_pool, total)
    sector_rollup = build_sector_rollup(all_holdings, equity_pool, total)
    console.print(f"[green]✓[/green] {len(stock_rollup)} unique stocks, {len(sector_rollup)} sectors")

    # ── Build Excel ───────────────────────────────────────────────────────────
    console.print(f"\n[bold]Step 7: Building Excel output: {args.output}...[/bold]")
    from src.excel_writer import ExcelWriter
    writer = ExcelWriter(total_portfolio=total)

    writer.add_true_allocation(rollup_df, exposure_df)
    writer.add_sub_class_breakdown(sub_rollup)
    writer.add_look_through_detail(exposure_df)

    if len(stock_rollup) > 0:
        writer.add_stock_rollup(stock_rollup, equity_pool)

    if len(sector_rollup) > 0:
        writer.add_sector_breakdown(sector_rollup)

    if cash_df is not None and len(cash_df) > 0:
        writer.add_cash_holdings(cash_df, total)

    writer.save(args.output)
    console.print(f"\n[bold green]✅ Analysis complete! Output saved to: {args.output}[/bold green]")

    # ── Summary stats ─────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold]Portfolio Summary[/bold]\n"
        f"Total Value:     ₹{total:,.0f}  ({total/100000:.1f}L)\n"
        f"Instruments:     {len(portfolio_df)}\n"
        f"Unique Stocks:   {len(stock_rollup)}\n"
        f"Sectors:         {len(sector_rollup)}\n"
        f"Equity:          {rollup_df[rollup_df['True Asset Class'].str.contains('Equity', na=False)]['Rs Exposure'].sum()/total*100:.1f}%\n"
        f"Debt:            {rollup_df[rollup_df['True Asset Class'].str.contains('Debt|Bond|LIC', na=False, regex=True)]['Rs Exposure'].sum()/total*100:.1f}%\n"
        f"Gold:            {rollup_df[rollup_df['True Asset Class']=='Gold']['Rs Exposure'].sum()/total*100:.1f}%\n"
        f"Cash:            {rollup_df[rollup_df['True Asset Class'].str.contains('Cash', na=False)]['Rs Exposure'].sum()/total*100:.1f}%",
        border_style='green'
    ))


if __name__ == '__main__':
    main()
