import pandas as pd

from scanner.core.peak import analyze_same_session_peak


def _bars(rows):
    return pd.DataFrame([
        {"timestamp_et": pd.Timestamp(ts, tz="America/New_York"), "open": o, "high": h, "low": l, "close": c}
        for ts, o, h, l, c in rows
    ])


def test_long_peak_reports_exact_minute_and_return():
    result = analyze_same_session_peak(
        _bars([
            ("2026-08-28 10:00", 10.0, 10.5, 9.9, 10.2),
            ("2026-08-28 10:07", 10.2, 12.0, 10.1, 11.8),
            ("2026-08-28 10:20", 11.8, 11.9, 11.0, 11.1),
        ]),
        entry_price=10.0,
        entry_timestamp="2026-08-28 10:00:00-04:00",
        direction="LONG",
        session_end="16:00",
    )
    assert result.peak_price == 12.0
    assert result.peak_return_pct == 0.2
    assert result.minutes_to_peak == 7


def test_short_peak_uses_low_as_maximum_profit():
    result = analyze_same_session_peak(
        _bars([
            ("2026-08-28 10:00", 10.0, 10.2, 9.8, 9.9),
            ("2026-08-28 10:12", 9.9, 10.0, 8.0, 8.2),
        ]),
        entry_price=10.0,
        entry_timestamp="2026-08-28 10:00:00-04:00",
        direction="SHORT",
        session_end="16:00",
    )
    assert result.peak_price == 8.0
    assert result.peak_return_pct == 0.2
    assert result.minutes_to_peak == 12


def test_peak_excludes_bars_at_or_after_session_end():
    result = analyze_same_session_peak(
        _bars([
            ("2026-08-28 15:59", 10.0, 10.5, 9.9, 10.4),
            ("2026-08-28 16:00", 10.4, 20.0, 10.4, 20.0),
        ]),
        entry_price=10.0,
        entry_timestamp="2026-08-28 15:59:00-04:00",
        direction="LONG",
        session_end="16:00",
    )
    assert result.peak_price == 10.5
