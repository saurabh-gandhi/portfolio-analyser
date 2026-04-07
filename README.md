# 📊 Indian Portfolio Analyser

A Python tool that takes any Indian investment portfolio CSV and produces a **full bottoms-up analysis** Excel workbook — looking through every wrapper (MFs, ETFs, EPF, PPF, NPS, LIC, REITs) to show your true economic exposure.

## What it produces

A 6-sheet Excel workbook:

| Sheet | Contents |
|-------|----------|
| 🏦 True Allocation | Asset class breakdown after look-through of all wrappers |
| 🗂 Sub-Class Breakdown | Large/Mid/Small cap, Debt duration, Gold form, Cash type |
| 🔬 Look-Through Detail | Every asset mapped to true economic exposure |
| 🔍 Stock Roll-Up | Bottoms-up: 700+ unique stocks ranked by ₹ exposure |
| 📊 Equity Sector Breakdown | Sector concentration across entire equity book |
| 💵 Cash & Debt Holdings | Cash, TREPS, CDs, CPs per fund |

## Quick Start

```bash
git clone https://github.com/yourusername/portfolio-analyser
cd portfolio-analyser
pip install -r requirements.txt

# Basic run
python run.py --portfolio data/sample/sample_portfolio.csv

# With PPFAS XLS (for accurate PPFCF/PPAF holdings)
python run.py --portfolio my_portfolio.csv --ppfas-xls PPFAS_Monthly_Portfolio_Feb_2026.xls --output analysis.xlsx
```

## Portfolio CSV Format

| Column | Description | Example |
|--------|-------------|---------|
| `Asset` | Instrument name | `PARAG PARIKH FLEXI CAP FUND - DIRECT PLAN` |
| `Asset Category` | Broad category | `Equity`, `Debt`, `Gold`, `Real Estate`, `Cash` |
| `Type` | Instrument type | `Mutual fund`, `ETF`, `Stock`, `Bond`, `Providend fund`, `NPS`, `LIC`, `Cash`, `Esops` |
| `Qty.` | Units/shares held | `28687.83` |
| `LTP` | Last traded price/NAV | `89.27` |
| `Present value` | Current value in ₹ | `2560963` |

See `data/sample/sample_portfolio.csv` for a working example.

## Configuration (`config/instrument_config.yaml`)

```yaml
lic_treatment:
  asset_class: "Debt — Insurance/LIC"
  maturity_year: 2030

nps_scheme:
  equity_pct: 75        # LC75. Use 50 for LC50, 25 for Conservative
  govt_bond_pct: 15
  corp_debt_pct: 10

arbitrage_funds:
  - "Parag Parikh Arbitrage Fund"
  - "Nippon India Arbitrage Fund"

reit_equity_pct: 80
```

## Data Sources

| Data | Source | Auth |
|------|--------|------|
| MF/ETF holdings | [mfdata.in](https://mfdata.in) | None |
| PPFAS holdings | AMC XLS (manual) | None |
| NAV data | [amfiindia.com](https://www.amfiindia.com) | None |

## Dependencies

See `requirements.txt`. Python 3.9+.
