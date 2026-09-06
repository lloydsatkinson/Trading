import pandas as pd

import scripts.run_strategy_research as runner


def test_parse_selection_maps_a1_to_orb_pullback_only():
    strategies, variants = runner._parse_selection("a1")

    assert strategies == ("orb",)
    assert variants == ("ORB_LONG_PULLBACK",)


def test_filter_signal_variants_keeps_only_a1_pullback_rows():
    signals = pd.DataFrame(
        [
            {"variant_id": "ORB_LONG_BREAK", "symbol": "AAA"},
            {"variant_id": "ORB_LONG_PULLBACK", "symbol": "BBB"},
            {"variant_id": "ORB_SHORT_FAILED_GAP", "symbol": "CCC"},
        ]
    )

    filtered = runner._filter_signal_variants(signals, ("ORB_LONG_PULLBACK",))

    assert list(filtered["variant_id"]) == ["ORB_LONG_PULLBACK"]
    assert list(filtered["symbol"]) == ["BBB"]
