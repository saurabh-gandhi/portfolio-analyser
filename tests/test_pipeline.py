"""Basic tests for the portfolio analysis pipeline."""
import pandas as pd
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.portfolio_loader import PortfolioLoader
from src.utils import normalise_stock_name, clean_number, bar_chart


# ── utils tests ───────────────────────────────────────────────────────────────

def test_normalise_stock_name():
    assert normalise_stock_name('HDFC Bank Limited') == 'HDFC BANK'
    assert normalise_stock_name('Infosys Ltd.') == 'INFOSYS'
    assert normalise_stock_name('Reliance Industries Limited') == 'RELIANCE INDUSTRIES'
    assert normalise_stock_name('') == ''
    assert normalise_stock_name(None) == ''


def test_clean_number():
    assert clean_number('₹1,23,456') == 123456.0
    assert clean_number('1234.56') == 1234.56
    assert clean_number('#DIV/0!') == 0.0
    assert clean_number(None) == 0.0
    assert clean_number('') == 0.0


def test_bar_chart():
    b = bar_chart(10.0, scale=2, width=20)
    assert len(b) == 20
    assert '█' in b
    assert b == '█████░░░░░░░░░░░░░░░'


# ── portfolio_loader tests ─────────────────────────────────────────────────────

def test_loader_sample_portfolio():
    loader = PortfolioLoader('data/sample/sample_portfolio.csv')
    df = loader.load()
    assert len(df) > 0
    assert 'PresentValue' in df.columns
    assert 'InstrumentClass' in df.columns
    assert loader.total_value > 0


def test_loader_instrument_classification():
    loader = PortfolioLoader('data/sample/sample_portfolio.csv')
    df = loader.load()
    classes = df['InstrumentClass'].unique()
    # Should detect these classes from sample
    for expected in ['mf', 'etf', 'stock', 'epf', 'ppf', 'nps', 'lic', 'cash', 'sgb']:
        assert expected in classes, f"Expected class '{expected}' not found. Got: {classes}"


def test_loader_zero_values_dropped():
    loader = PortfolioLoader('data/sample/sample_portfolio.csv')
    df = loader.load()
    assert (df['PresentValue'] > 0).all(), "Zero-value rows should be dropped"


def test_loader_required_columns_missing(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("Foo,Bar\n1,2\n")
    loader = PortfolioLoader(str(bad_csv))
    with pytest.raises(ValueError, match="missing required columns"):
        loader.load()


# ── true_exposure tests ────────────────────────────────────────────────────────

def test_true_exposure_epf():
    import yaml
    from src.true_exposure import compute_true_exposure
    with open('config/instrument_config.yaml') as f:
        config = yaml.safe_load(f)

    df = pd.DataFrame([{
        'AssetName': 'My EPF',
        'PresentValue': 100000,
        'InstrumentClass': 'epf',
        'TypeNorm': 'providend fund',
        'CategoryNorm': 'debt',
    }])
    exposure_df, rollup_df = compute_true_exposure(df, config)
    classes = set(rollup_df['True Asset Class'])
    assert 'Indian Equity' in classes
    assert 'Indian Govt Bonds' in classes
    assert 'Indian Corp Debt / CDs' in classes
    # Equity should be ~15% of 100000 = 15000
    eq_row = rollup_df[rollup_df['True Asset Class'] == 'Indian Equity']
    assert abs(float(eq_row['Rs Exposure'].values[0]) - 15000) < 1


def test_true_exposure_ppf():
    import yaml
    from src.true_exposure import compute_true_exposure
    with open('config/instrument_config.yaml') as f:
        config = yaml.safe_load(f)

    df = pd.DataFrame([{
        'AssetName': 'PPF',
        'PresentValue': 200000,
        'InstrumentClass': 'ppf',
        'TypeNorm': 'providend fund',
        'CategoryNorm': 'debt',
    }])
    exposure_df, rollup_df = compute_true_exposure(df, config)
    assert len(rollup_df) == 1
    assert rollup_df.iloc[0]['True Asset Class'] == 'Indian Govt Bonds'
    assert rollup_df.iloc[0]['Rs Exposure'] == 200000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
