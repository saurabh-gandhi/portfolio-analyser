"""Shared utilities: name normalisation, formatting helpers."""
import re
import pandas as pd


# ── Stock name normalisation ──────────────────────────────────────────────────
_SUFFIXES = [
    ' limited', ' ltd', ' ltd.', ' corporation', ' corp', ' inc', ' inc.',
    ' plc', ' co.', ' & co', ' co', ' pvt', ' private',
]

_MANUAL_MAP = {
    'HDFC BANK': 'HDFC BANK',
    'ICICI BANK': 'ICICI BANK',
    'AXIS BANK': 'AXIS BANK',
    'STATE BANK OF INDIA': 'STATE BANK OF INDIA',
    'BHARTI AIRTEL': 'BHARTI AIRTEL',
    'RELIANCE INDUSTRIES': 'RELIANCE INDUSTRIES',
    'INFOSYS': 'INFOSYS',
    'KOTAK MAHINDRA BANK': 'KOTAK MAHINDRA BANK',
    'LARSEN & TOUBRO': 'LARSEN & TOUBRO',
    'TATA CONSULTANCY SERVICES': 'TATA CONSULTANCY SERVICES',
    'HINDUSTAN UNILEVER': 'HINDUSTAN UNILEVER',
    'NVIDIA': 'NVIDIA',
    'APPLE': 'APPLE',
    'MICROSOFT': 'MICROSOFT',
    'AMAZON': 'AMAZON',
    'ALPHABET': 'ALPHABET',
    'META PLATFORMS': 'META PLATFORMS',
}


def normalise_stock_name(name: str) -> str:
    """Normalise stock/company name for deduplication across data sources."""
    if pd.isna(name):
        return ''
    n = str(name).strip().upper()
    for suffix in _SUFFIXES:
        n = re.sub(re.escape(suffix) + r'\s*$', '', n, flags=re.IGNORECASE)
    n = re.sub(r'\s+', ' ', n).strip()
    for key, val in _MANUAL_MAP.items():
        if n.startswith(key):
            return val
    return n


def clean_number(x) -> float:
    """Parse ₹ value strings to float."""
    if pd.isna(x):
        return 0.0
    s = str(x).replace(',', '').replace('₹', '').replace('%', '').strip()
    # Handle DIV/0! and other errors
    if s in ['#DIV/0!', '#N/A', '#VALUE!', '#REF!', 'nan', '', '-']:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def bar_chart(pct: float, scale: float = 2.0, width: int = 20) -> str:
    """Return a Unicode block bar string for Excel cells."""
    n = max(0, min(width, round(pct / scale)))
    return '█' * n + '░' * (width - n)


def best_sector(sectors: list) -> str:
    """Pick the most meaningful sector label from a list (prefer Morningstar-style)."""
    preferred = [
        'Financial Services', 'Technology', 'Consumer Cyclical', 'Industrials',
        'Basic Materials', 'Healthcare', 'Consumer Defensive', 'Energy',
        'Utilities', 'Communication Services', 'Real Estate', 'Banks',
    ]
    clean = [s for s in sectors if s and str(s) not in ('nan', '')]
    for p in preferred:
        if p in clean:
            return p
    return clean[0] if clean else ''


def fmt_lakhs(value: float) -> str:
    """Format ₹ value as lakhs string."""
    return f"₹{value / 100_000:.2f}L"
