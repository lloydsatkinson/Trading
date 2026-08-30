import numpy as np

from scanner.serclick.study import _safe_symbol


def test_safe_symbol_rejects_missing_and_non_string_values():
    assert _safe_symbol(np.nan) is False
    assert _safe_symbol(None) is False
    assert _safe_symbol(123.0) is False
    assert _safe_symbol("ABCD") is True
