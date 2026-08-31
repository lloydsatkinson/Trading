import numpy as np

from scanner.core.models import price_bucket
from scanner.strategies.dan_irish.features import retained_gain_ratio


def test_dan_price_bucket_boundaries():
    assert price_bucket(0.99) == "LT_1"
    assert price_bucket(1.00) == "1_2"
    assert price_bucket(1.99) == "1_2"
    assert price_bucket(2.00) == "2_5"
    assert price_bucket(5.00) == "5_10"
    assert price_bucket(10.00) == "10_20"
    assert price_bucket(20.00) == "20_50"
    assert price_bucket(50.00) == "50_100"
    assert price_bucket(100.00) == "GE_100"
    assert price_bucket(None) == "UNKNOWN"
    assert price_bucket(0) == "UNKNOWN"


def test_retained_gain_ratio_and_invalid_denominator():
    assert retained_gain_ratio(2.0, 6.0, 5.0) == 0.75
    assert np.isnan(retained_gain_ratio(4.0, 4.0, 4.0))
    assert np.isnan(retained_gain_ratio(None, 6.0, 5.0))
