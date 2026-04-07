#!/usr/bin/env python3
"""
main.py — Indian Portfolio Analyser
CLI entry point. Orchestrates the full pipeline:
  load → classify → fetch → exposure → subclass → stock rollup → report
"""

import sys
import argparse
from pathlib import Path

# Add src to path when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.portfolio_loader import load_portfolio, portfolio_summary
from src.instrument_registry import classify_portfolio
from src.holdings_fetcher import fetch_all_holdings
from src.exposure_engine import compute_all_exposures
from src.subclass_engine import build_subclass_breakdown
from src.stock_aggregator import build_stock_rollup, build_sector_rollup
from src.report_builder import build_report

import pandas as pd


def build_rollup_df(exposure_rows: list, total: float) -> pd.DataFrame:
    """Aggregate exposure rows into asset-class level rollup."""
    from collections import defaultdict
    buckets: dict[str, list] = defaultdict(list)
    for row in exposure_rows:
        ac = row.true_asset_class
        # Normalise to top-level class
        ac_top = _normalise_ac(ac)
        buckets[ac_top].append(row)

    rows = []
    for ac, exp_rows in buckets.items():
        rs = sum(r.rs_exposure for r in exp_rows)
        notes = "; ".join(set(r.notes for r in exp_rows if r.notes))[:120]
        rows.append({
            "True Asset Class": ac,
            "Rs Exposure": round(rs, 0),
            "Pct of Total": round(rs / total * 100, 2),
            "Notes": notes,
        })

    df = pd.DataFrame(rows).sort_values("Rs Exposure", ascending=False).reset_index(drop=True)
    return df


def _normalise_ac(ac: str) -> str:
    """Collapse sub-class labels into top-level asset classes for the rollup sheet."""
    ac_upper = ac.upper()
    if "EQUITY — LARGE" in ac_upper: return "Indian Equity — Large Cap"
    if "EQUITY — MID"   in ac_upper: return "Indian Equity — Mid Cap"
    if "EQUITY — SMALL" in ac_upper: return "Indian Equity — Small Cap"
    if "EQUITY — UNLISTED" in ac_upper or "PRIVATE" in ac_upper: return "Indian Equity — Unlisted / Private"
    if "INDIAN EQUITY" in ac_upper:  return "Indian Equity"
    if "US/INTL EQUITY" in ac_upper or "US EQUITY" in ac_upper: return "US/Intl Equity — Large/Mega Cap"
    if "COMMERCIAL REAL ESTATE" in ac_upper: return "Commercial Real Estate"
    if "GOVT BONDS" in ac_upper:     return "Indian Govt Bonds — Long Term"
    if "CORP DEBT" in ac_upper and ("LONG" in ac_upper or "EPF" in ac_upper or
                                     "REIT" in ac_upper or "NPS" in ac_upper):
        return "Indian Corp Debt — Long Term"
    if "CORP DEBT" in ac_upper:      return "Indian Corp Debt — Short Term"
    if "LIC" in ac_upper or "INSURANCE" in ac_upper: return ac  # keep full label with year
    if "GOLD — SGB" in ac_upper or "SOVEREIGN GOLD" in ac_upper: return "Gold — Sovereign Gold Bonds (Paper)"
    if "GOLD — PHYSICAL" in ac_upper: return "Gold — Physical"
    if "GOLD — ETF" in ac_upper:     return "Gold — ETF (Paper)"
    if "ARBITRAGE" in ac_upper:      return "Cash & Equivalents (Arbitrage)"
    if "BANK" in ac_upper:           return "Cash — Bank / Savings Account"
    if "RENTAL" in ac_upper:         return "Cash — Rental Deposit / Receivable"
    if "CASH" in ac_upper:           return "Cash & Equivalents"
    return ac  # return as-is if no match


def run(input_path: str, output_path: str,
        ppfas_xls: str = None,
        quiet: bool = False):
    """Run the full analysis pipeline."""
    print("\n" + "="*65)
    print("  🏛  Indian Portfolio Analyser")
    print("="*65)

    # ── 1. Load ──────────────────────────────────────────────────────────────
    print("\n[1/6] Loading portfolio...")
    df = load_portfolio(input_path)
    if not quiet:
        portfolio_summary(df)
    total = float(df["Present Value"].sum())

    # ── 2. Classify ──────────────────────────────────────────────────────────
    print("[2/6] Classifying instruments...")
    profiles = classify_portfolio(df)

    # ── 3. Fetch holdings ────────────────────────────────────────────────────
    print("[3/6] Fetching constituent holdings...")
    holdings_map = fetch_all_holdings(profiles, ppfas_xls_path=ppfas_xls)

    # ── 4. Compute exposures ─────────────────────────────────────────────────
    print("[4/6] Computing true economic exposure...")
    exposure_rows = compute_all_exposures(profiles, holdings_map)

    # ── 5. Build aggregations ────────────────────────────────────────────────
    print("[5/6] Building aggregations...")
    rollup_df   = build_rollup_df(exposure_rows, total)
    subclass_df = build_subclass_breakdown(profiles, exposure_rows, total)
    stock_df    = build_stock_rollup(profiles, holdings_map, total, exclude_arbitrage=True)
    sector_df   = build_sector_rollup(stock_df, total)

    print(f"\n  Asset classes: {len(rollup_df)}")
    print(f"  Sub-classes:   {len(subclass_df)}")
    print(f"  Unique stocks: {len(stock_df)}")
    print(f"  Sectors:       {len(sector_df)}")

    # ── 6. Build report ──────────────────────────────────────────────────────
    print(f"\n[6/6] Building Excel report → {output_path}")
    build_report(
        output_path=output_path,
        rollup_df=rollup_df,
        subclass_df=subclass_df,
        stock_df=stock_df,
        sector_df=sector_df,
        exposure_rows=exposure_rows,
        total_portfolio_value=total,
    )

    print(f"\n{'='*65}")
    print(f"  ✅  Analysis complete!")
    print(f"  📄  Output: {output_path}")
    print(f"  💰  Total portfolio: ₹{total/100000:.2f}L")
    print(f"{'='*65}\n")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Indian Portfolio Analyser — bottoms-up look-through analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --input data/sample/portfolio_sample.csv
  python main.py --input my_portfolio.csv --output analysis.xlsx
  python main.py --input my_portfolio.csv --ppfas-xls data/ppfas_feb2026.xls
        """,
    )
    parser.add_argument("--input",  "-i",  help="Path to portfolio CSV", default=None)
    parser.add_argument("--output", "-o",  help="Output Excel path", default="portfolio_analysis.xlsx")
    parser.add_argument("--ppfas-xls",     help="Path to PPFAS monthly XLS (optional)", default=None)
    parser.add_argument("--quiet",  "-q",  help="Suppress verbose output", action="store_true")

    args = parser.parse_args()

    # Prompt if no input provided
    input_path = args.input
    if not input_path:
        input_path = input("Enter path to portfolio CSV: ").strip()

    if not Path(input_path).exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    run(
        input_path=input_path,
        output_path=args.output,
        ppfas_xls=args.ppfas_xls,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
