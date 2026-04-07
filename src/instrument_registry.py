"""
instrument_registry.py
Classifies each portfolio asset into an instrument type and determines
the data-fetch strategy for its underlying constituents.
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


CONFIG_DIR = Path(__file__).parent.parent / "config"

# ── Instrument types ──────────────────────────────────────────────────────────
class InstrumentType:
    INDIAN_MF        = "indian_mf"          # Indian mutual fund (fetch from mfdata.in)
    INDIAN_ETF       = "indian_etf"         # Indian ETF (index-based, from mfdata.in)
    DIRECT_STOCK_IN  = "direct_stock_in"    # Indian listed stock
    DIRECT_STOCK_US  = "direct_stock_us"    # US listed stock (NVDA, AAPL, etc.)
    REIT             = "reit"               # Indian REIT
    SGB              = "sgb"                # Sovereign Gold Bond
    GOLD_ETF         = "gold_etf"           # Gold ETF (GOLDBEES etc.)
    GOLD_PHYSICAL    = "gold_physical"      # Physical gold
    EPF              = "epf"                # Employee Provident Fund
    PPF              = "ppf"                # Public Provident Fund
    NPS              = "nps"                # National Pension Scheme
    LIC              = "lic"                # LIC / Insurance policy
    ESOP             = "esop"               # ESOPs / unlisted equity
    ARBITRAGE_MF     = "arbitrage_mf"       # Arbitrage fund (hedged, ~0 equity)
    BANK_ACCOUNT     = "bank_account"       # Bank / savings account
    RENTAL           = "rental"             # Rental deposit / receivable
    DEBT_BOND        = "debt_bond"          # Generic debt / bonds
    US_ETF           = "us_etf"             # US-listed ETF (QQQ, SPY, VOO etc.)
    UNKNOWN          = "unknown"


@dataclass
class InstrumentProfile:
    asset_name: str
    present_value: float
    instrument_type: str
    fetch_strategy: str              # "mfdata_api", "etf_registry", "single_asset", "manual_config", "skip"
    amfi_family_id: Optional[int] = None
    amfi_code: Optional[str] = None
    config_override: dict = field(default_factory=dict)
    notes: str = ""


# ── Known instrument registries ───────────────────────────────────────────────
KNOWN_INDIAN_ETFS = {
    # ETF ticker → mfdata.in family_id
    "NIFTYBEES":     {"family_id": 2072,  "index": "Nifty 50"},
    "JUNIORBEES":    {"family_id": 2085,  "index": "Nifty Next 50"},
    "MIDCAPETF":     {"family_id": 4613,  "index": "Nifty Midcap 150"},
    "MON100":        {"family_id": 7356,  "index": "Nasdaq 100"},
    "MAFANG":        {"family_id": 7356,  "index": "Nasdaq 100"},  # approximate
    "GOLDBEES":      {"family_id": None,  "index": "Gold", "type": InstrumentType.GOLD_ETF},
    "LIQUIDBEES":    {"family_id": None,  "index": "Liquid", "type": InstrumentType.ARBITRAGE_MF},
    "LOWVOLIETF":    {"family_id": 2072,  "index": "Nifty 100 Low Vol"},
    "BANKBEES":      {"family_id": None,  "index": "Nifty Bank"},
    "ITBEES":        {"family_id": None,  "index": "Nifty IT"},
    "SETFNIF50":     {"family_id": 2072,  "index": "Nifty 50"},    # SBI ETF
    "UTINIFTETF":    {"family_id": 5808,  "index": "Nifty 50"},    # UTI
    "ICICIB22":      {"family_id": None,  "index": "Bharat Bond 2022"},
    "EBBETF0433":    {"family_id": None,  "index": "Bharat Bond 2033"},
}

KNOWN_US_ETFS = {"QQQ", "SPY", "VOO", "VTI", "IVV", "VGT", "ARKK", "SCHD", "VIG"}
KNOWN_US_STOCKS = {"NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NFLX"}

KNOWN_REITS = {"BIRET-RR", "BIRET", "EMBASSY-RR", "EMBASSY", "KRT-RR", "KRT",
               "NEXUS-RR", "MINDSPACE-RR", "PLATINDREIT"}

SGB_PATTERN = re.compile(r"^SGB[A-Z]{3}\d{2}", re.IGNORECASE)

ARBITRAGE_KEYWORDS = ["arbitrage", "arb fund"]


def _load_overrides() -> dict:
    """Load instrument_overrides.yaml."""
    path = CONFIG_DIR / "instrument_overrides.yaml"
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
            return {k.lower(): v for k, v in data.get("instruments", {}).items()}
    return {}


def _is_arbitrage(name: str, asset_type: str) -> bool:
    name_lower = name.lower()
    return any(kw in name_lower for kw in ARBITRAGE_KEYWORDS)


def _is_sgb(name: str, asset_type: str) -> bool:
    return bool(SGB_PATTERN.match(name.strip()))


def _is_mf(asset_type: str) -> bool:
    return asset_type.lower() in {"mutual fund", "mf", "fund"}


def _is_etf(asset_type: str) -> bool:
    return asset_type.lower() in {"etf", "exchange traded fund"}


def _is_direct_stock(asset_type: str) -> bool:
    return asset_type.lower() in {"stock", "share", "equity", "esops"}


def classify_instrument(asset_name: str, present_value: float,
                        asset_category: str, asset_type: str) -> InstrumentProfile:
    """
    Classify a single asset and return an InstrumentProfile with fetch strategy.
    """
    overrides = _load_overrides()
    name_key = asset_name.lower().strip()
    name_upper = asset_name.upper().strip()

    # ── 1. Check explicit overrides first ────────────────────────────────────
    if name_key in overrides:
        cfg = overrides[name_key]
        itype_str = cfg.get("type", "unknown").lower()
        type_map = {
            "nps": InstrumentType.NPS,
            "epf": InstrumentType.EPF,
            "ppf": InstrumentType.PPF,
            "lic": InstrumentType.LIC,
            "arbitrage_fund": InstrumentType.ARBITRAGE_MF,
            "esop": InstrumentType.ESOP,
            "bank_account": InstrumentType.BANK_ACCOUNT,
            "rental": InstrumentType.RENTAL,
            "debt": InstrumentType.DEBT_BOND,
            "us_etf": InstrumentType.US_ETF,
            "indian_mf": InstrumentType.INDIAN_MF,
        }
        itype = type_map.get(itype_str, InstrumentType.UNKNOWN)
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=itype, fetch_strategy="manual_config",
            config_override=cfg,
            notes=f"Manual override: type={itype_str}"
        )

    # ── 2. SGB detection ─────────────────────────────────────────────────────
    if _is_sgb(asset_name, asset_type) or (asset_category.lower() == "gold" and "sgb" in name_key):
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.SGB,
            fetch_strategy="single_asset",
            notes="Sovereign Gold Bond → 100% gold"
        )

    # ── 3. Known REITs ───────────────────────────────────────────────────────
    if name_upper in KNOWN_REITS or (asset_category.lower() == "real estate" and _is_direct_stock(asset_type)):
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.REIT,
            fetch_strategy="single_asset",
            notes="REIT → 80% commercial RE / 20% debt"
        )

    # ── 4. Known US ETFs / US stocks ─────────────────────────────────────────
    if name_upper in KNOWN_US_ETFS:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.US_ETF,
            fetch_strategy="etf_registry",
            notes=f"US ETF → Nasdaq/S&P 500 constituents"
        )
    if name_upper in KNOWN_US_STOCKS:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.DIRECT_STOCK_US,
            fetch_strategy="single_asset",
            notes="US listed stock → 100% US large cap equity"
        )

    # ── 5. Known Indian ETFs ─────────────────────────────────────────────────
    if name_upper in KNOWN_INDIAN_ETFS:
        info = KNOWN_INDIAN_ETFS[name_upper]
        itype = info.get("type", InstrumentType.INDIAN_ETF)
        fid = info.get("family_id")
        strategy = "mfdata_api" if fid else "etf_registry"
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=itype,
            fetch_strategy=strategy,
            amfi_family_id=fid,
            notes=f"Indian ETF → {info['index']}"
        )

    # ── 6. Physical gold ─────────────────────────────────────────────────────
    if asset_category.lower() == "gold" and "physical" in name_key:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.GOLD_PHYSICAL,
            fetch_strategy="single_asset",
            notes="Physical gold"
        )

    # ── 7. Arbitrage mutual fund ─────────────────────────────────────────────
    if _is_mf(asset_type) and _is_arbitrage(asset_name, asset_type):
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.ARBITRAGE_MF,
            fetch_strategy="mfdata_api",
            notes="Arbitrage fund → excluded from equity analysis"
        )

    # ── 8. Indian mutual fund → look up AMFI and fetch from mfdata.in ────────
    if _is_mf(asset_type) or _is_etf(asset_type):
        itype = InstrumentType.INDIAN_MF if _is_mf(asset_type) else InstrumentType.INDIAN_ETF
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=itype,
            fetch_strategy="mfdata_api_search",  # will search by name
            notes="Indian MF/ETF → search mfdata.in for family_id"
        )

    # ── 9. EPF / PPF / NPS ───────────────────────────────────────────────────
    type_lower = asset_type.lower()
    if type_lower in {"providend fund", "provident fund", "epf"}:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.EPF,
            fetch_strategy="manual_config",
            notes="EPF → 15% large cap equity / 55% G-Secs / 30% corp bonds"
        )
    if type_lower == "ppf":
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.PPF,
            fetch_strategy="manual_config",
            notes="PPF → 100% Indian Govt Bonds (Long Term)"
        )
    if type_lower == "nps":
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.NPS,
            fetch_strategy="manual_config",
            notes="NPS → splits depend on scheme (LC75 default)"
        )
    if type_lower == "lic":
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.LIC,
            fetch_strategy="manual_config",
            notes="LIC → configure treatment in instrument_overrides.yaml"
        )

    # ── 10. Direct Indian stocks ─────────────────────────────────────────────
    if _is_direct_stock(asset_type) and asset_category.lower() == "equity":
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.DIRECT_STOCK_IN,
            fetch_strategy="single_asset",
            notes="Indian listed stock → 100% Indian equity"
        )

    # ── 11. Cash ─────────────────────────────────────────────────────────────
    if asset_category.lower() == "cash" or type_lower in {"cash", "savings"}:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.BANK_ACCOUNT,
            fetch_strategy="single_asset",
            notes="Cash / bank account"
        )

    # ── 12. Generic debt ─────────────────────────────────────────────────────
    if asset_category.lower() == "debt" or type_lower in {"bond", "fd", "ncd", "debenture"}:
        return InstrumentProfile(
            asset_name=asset_name, present_value=present_value,
            instrument_type=InstrumentType.DEBT_BOND,
            fetch_strategy="manual_config",
            notes="Debt instrument → configure duration in instrument_overrides.yaml"
        )

    # ── 13. Unknown ──────────────────────────────────────────────────────────
    return InstrumentProfile(
        asset_name=asset_name, present_value=present_value,
        instrument_type=InstrumentType.UNKNOWN,
        fetch_strategy="skip",
        notes=f"⚠️ Unclassified: category={asset_category}, type={asset_type}. Add to instrument_overrides.yaml"
    )


def classify_portfolio(df) -> list[InstrumentProfile]:
    """Classify all assets in the portfolio DataFrame."""
    profiles = []
    unknown = []
    for _, row in df.iterrows():
        p = classify_instrument(
            asset_name=row["Asset"],
            present_value=float(row["Present Value"]),
            asset_category=str(row.get("Asset Category", "Unknown")),
            asset_type=str(row.get("Type", "Unknown")),
        )
        profiles.append(p)
        if p.instrument_type == InstrumentType.UNKNOWN:
            unknown.append(p.asset_name)

    if unknown:
        print(f"\n[instrument_registry] ⚠️  {len(unknown)} unclassified instruments:")
        for name in unknown:
            print(f"    - {name}")
        print("  → Add these to config/instrument_overrides.yaml\n")

    return profiles
