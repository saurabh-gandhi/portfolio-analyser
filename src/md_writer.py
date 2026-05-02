"""Generate a Markdown report alongside the Excel output."""
import pandas as pd
from datetime import date
from pathlib import Path


def _fmt_lakhs(val: float) -> str:
    if val >= 1_00_00_000:
        return f"₹{val / 1_00_00_000:.2f}Cr"
    if val >= 1_00_000:
        return f"₹{val / 1_00_000:.2f}L"
    return f"₹{val:,.0f}"


def _bar(pct: float, scale: float = 3, width: int = 25) -> str:
    filled = min(round(pct / scale), width)
    return "█" * filled + "░" * (width - filled)


def build_markdown(
    portfolio_df: pd.DataFrame,
    rollup_df: pd.DataFrame,
    sub_rollup: pd.DataFrame,
    stock_rollup: pd.DataFrame,
    sector_rollup: pd.DataFrame,
    all_holdings: pd.DataFrame,
    total: float,
    output_path: str,
) -> str:
    lines = []
    today = date.today().strftime("%-d %B %Y")

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "# Portfolio Analysis",
        f"**Generated:** {today}  ",
        f"**Total Portfolio Value:** {_fmt_lakhs(total)}  ",
        f"**Instruments:** {len(portfolio_df)}",
        "",
    ]

    # ── Original Holdings ─────────────────────────────────────────────────────
    lines += ["## Original Holdings", ""]
    df = portfolio_df.copy()
    df['_cat'] = df['Asset Category'].fillna('Other').str.strip()
    cat_totals = df.groupby('_cat')['PresentValue'].sum().sort_values(ascending=False)

    for cat, cat_total in cat_totals.items():
        cat_df = df[df['_cat'] == cat].sort_values('PresentValue', ascending=False)
        lines.append(f"### {cat} — {_fmt_lakhs(cat_total)} ({cat_total / total * 100:.1f}%)")
        lines.append("")
        lines.append("| # | Asset | Type | Present Value | % of Portfolio |")
        lines.append("|---|-------|------|--------------|---------------|")
        for rank, (_, r) in enumerate(cat_df.iterrows(), 1):
            pv = float(r['PresentValue'])
            lines.append(
                f"| {rank} | {r.get('AssetName', r.get('Asset', ''))} "
                f"| {r.get('Type', '')} "
                f"| {_fmt_lakhs(pv)} "
                f"| {pv / total * 100:.2f}% |"
            )
        lines.append("")

    # ── True Asset Allocation ─────────────────────────────────────────────────
    lines += ["## True Asset Allocation (Look-Through)", ""]
    lines.append("| Asset Class | ₹ Exposure | % of Portfolio | Bar |")
    lines.append("|-------------|-----------|---------------|-----|")
    for _, r in rollup_df.iterrows():
        pct = float(r['Pct of Total'])
        lines.append(
            f"| {r['True Asset Class']} "
            f"| {_fmt_lakhs(float(r['Rs Exposure']))} "
            f"| {pct:.1f}% "
            f"| `{_bar(pct)}` |"
        )
    lines.append("")

    # ── Sub-Class Breakdown ───────────────────────────────────────────────────
    if sub_rollup is not None and len(sub_rollup) > 0:
        lines += ["## Sub-Class Breakdown", ""]
        lines.append("| Sub-Class | ₹ Exposure | % of Portfolio |")
        lines.append("|-----------|-----------|---------------|")
        for _, r in sub_rollup.iterrows():
            lines.append(
                f"| {r.get('Sub Class', '')} "
                f"| {_fmt_lakhs(float(r.get('Rs Exposure', 0)))} "
                f"| {float(r.get('Pct of Total', 0)):.2f}% |"
            )
        lines.append("")

    # ── Sector Breakdown ──────────────────────────────────────────────────────
    if sector_rollup is not None and len(sector_rollup) > 0:
        lines += ["## Equity Sector Breakdown", ""]
        lines.append("| # | Sector | Stocks | ₹ Exposure | % of Equity | % of Portfolio |")
        lines.append("|---|--------|--------|-----------|------------|---------------|")
        for _, r in sector_rollup.iterrows():
            lines.append(
                f"| {int(r.get('Rank', 0))} "
                f"| {r.get('Industry', r.get('Sector', ''))} "
                f"| {int(r.get('Stock_Count', 0))} "
                f"| {_fmt_lakhs(float(r.get('Total_Rs', 0)))} "
                f"| {float(r.get('Pct of Equity Pool', 0)):.1f}% "
                f"| {float(r.get('Pct of Total Portfolio', 0)):.2f}% |"
            )
        lines.append("")

    # ── Top 30 Stocks ─────────────────────────────────────────────────────────
    if stock_rollup is not None and len(stock_rollup) > 0:
        top_n = stock_rollup.head(30)
        lines += [f"## Top {len(top_n)} Stock Positions", ""]
        lines.append("| Rank | Stock | Sector | ₹ Exposure | % of Portfolio | % of Equity |")
        lines.append("|------|-------|--------|-----------|---------------|------------|")
        for _, r in top_n.iterrows():
            lines.append(
                f"| {int(r['Rank'])} "
                f"| {r.get('Stock Name', '')} "
                f"| {r.get('Sector', '')} "
                f"| {_fmt_lakhs(float(r.get('Total ₹ Exposure', 0)))} "
                f"| {float(r.get('Pct of Total Portfolio', 0)):.2f}% "
                f"| {float(r.get('Pct of Equity Pool', 0)):.1f}% |"
            )
        lines.append("")

    # ── Instrument → Stock ────────────────────────────────────────────────────
    if all_holdings is not None and len(all_holdings) > 0:
        lines += ["## Instrument → Stock Breakdown", ""]
        fund_totals = (
            all_holdings.groupby('Fund')['Weighted ₹ Exposure']
            .sum()
            .sort_values(ascending=False)
        )
        for fund_name, fund_total in fund_totals.items():
            fund_df = (
                all_holdings[all_holdings['Fund'] == fund_name]
                .sort_values('Weighted ₹ Exposure', ascending=False)
                .reset_index(drop=True)
            )
            fund_value = fund_df['Fund Value (₹)'].iloc[0] if 'Fund Value (₹)' in fund_df.columns else fund_total
            data_src = fund_df['Data Source'].iloc[0] if 'Data Source' in fund_df.columns else ''

            lines.append(f"### {fund_name} — {_fmt_lakhs(fund_value)}")
            if data_src:
                lines.append(f"*Data: {data_src}*")
            lines.append("")
            lines.append("| # | Stock | Sector | % to NAV | ₹ Exposure |")
            lines.append("|---|-------|--------|---------|-----------|")
            for rank, (_, h) in enumerate(fund_df.iterrows(), 1):
                lines.append(
                    f"| {rank} "
                    f"| {h.get('Stock Name', '')} "
                    f"| {h.get('Industry', '')} "
                    f"| {float(h.get('% to NAV', 0)):.2f}% "
                    f"| {_fmt_lakhs(float(h.get('Weighted ₹ Exposure', 0)))} |"
                )
            lines.append("")

    return "\n".join(lines)


def save_markdown(
    portfolio_df: pd.DataFrame,
    rollup_df: pd.DataFrame,
    sub_rollup: pd.DataFrame,
    stock_rollup: pd.DataFrame,
    sector_rollup: pd.DataFrame,
    all_holdings: pd.DataFrame,
    total: float,
    output_path: str,
):
    md = build_markdown(
        portfolio_df, rollup_df, sub_rollup, stock_rollup,
        sector_rollup, all_holdings, total, output_path,
    )
    md_path = Path(output_path).with_suffix('.md')
    md_path.write_text(md, encoding='utf-8')
    return str(md_path)
