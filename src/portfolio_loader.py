"""Load and validate portfolio CSV input."""
import pandas as pd
from pathlib import Path
from .utils import clean_number


REQUIRED_COLUMNS = {'Asset', 'Asset Category', 'Type', 'Present value'}

# Instrument type classifications
MF_TYPES       = {'mutual fund', 'mf'}
ETF_TYPES      = {'etf', 'exchange traded fund'}
STOCK_TYPES    = {'stock', 'share', 'equity'}
BOND_TYPES     = {'bond', 'ncd', 'debenture'}
EPF_TYPES      = {'providend fund', 'provident fund', 'epf', 'pf'}
NPS_TYPES      = {'nps', 'national pension'}
LIC_TYPES      = {'lic', 'insurance', 'endowment'}
CASH_TYPES     = {'cash', 'bank', 'savings', 'fd', 'fixed deposit'}
ESOP_TYPES     = {'esops', 'esop', 'stock option', 'rsu'}
REIT_TYPES     = {'reit', 'real estate investment trust'}
GOLD_ETF       = {'goldbees', 'gold etf', 'nippon gold etf', 'hdfc gold etf'}


class PortfolioLoader:
    def __init__(self, csv_path: str):
        self.path = Path(csv_path)
        self.df = None
        self.total_value = 0.0

    def load(self) -> pd.DataFrame:
        """Load, validate and enrich portfolio CSV."""
        df = pd.read_csv(self.path)

        # Rename first column if it has no header (Google Sheets export quirk)
        if df.columns[0].startswith('Unnamed') or df.columns[0] == 'A1':
            df = df.rename(columns={df.columns[0]: 'Asset'})

        # Strip whitespace from column names
        df.columns = [c.strip() for c in df.columns]

        # Validate required columns
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        # Clean present value
        df['PresentValue'] = df['Present value'].apply(clean_number)

        # Normalise type to lowercase for matching
        df['TypeNorm'] = df['Type'].fillna('').str.lower().str.strip()
        df['CategoryNorm'] = df['Asset Category'].fillna('').str.lower().str.strip()
        df['AssetName'] = df['Asset'].fillna('').str.strip()

        # Classify each row
        df['InstrumentClass'] = df.apply(self._classify, axis=1)

        # Drop zero-value rows
        df = df[df['PresentValue'] > 0].copy()
        df = df.reset_index(drop=True)

        self.df = df
        self.total_value = df['PresentValue'].sum()
        return df

    def _classify(self, row) -> str:
        t = row['TypeNorm']
        name = row['AssetName'].lower()
        cat = row['CategoryNorm']

        if any(k in t for k in EPF_TYPES):
            return 'epf'
        if any(k in t for k in NPS_TYPES):
            return 'nps'
        if any(k in t for k in LIC_TYPES):
            return 'lic'
        if any(k in t for k in ESOP_TYPES):
            return 'esops'
        if 'gold' in cat and t in BOND_TYPES | {'bond'}:
            return 'sgb'          # sovereign gold bond
        if any(k in name for k in GOLD_ETF):
            return 'gold_etf'
        if 'gold' in cat:
            return 'gold_physical'
        if 'real estate' in cat or any(k in t for k in REIT_TYPES):
            return 'reit'
        if 'ppf' in name or ('providend' in t and 'ppf' in name):
            return 'ppf'
        if any(k in t for k in EPF_TYPES):
            return 'epf'
        if any(k in t for k in MF_TYPES):
            return 'mf'
        if any(k in t for k in ETF_TYPES):
            return 'etf'
        if any(k in t for k in STOCK_TYPES):
            return 'stock'
        if any(k in t for k in BOND_TYPES):
            return 'bond'
        if any(k in t for k in CASH_TYPES):
            return 'cash'
        if 'rental' in name or 'rental' in t:
            return 'cash'
        return 'other'

    def get_instruments_by_class(self, cls: str) -> pd.DataFrame:
        """Filter rows by InstrumentClass."""
        return self.df[self.df['InstrumentClass'] == cls].copy()

    def summary(self) -> dict:
        counts = self.df.groupby('InstrumentClass')['PresentValue'].agg(['count', 'sum'])
        return {
            'total_value': self.total_value,
            'row_count': len(self.df),
            'by_class': counts.to_dict('index'),
        }
