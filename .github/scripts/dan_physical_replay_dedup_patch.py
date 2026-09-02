from pathlib import Path

path = Path("scripts/run_strategy_research.py")
text = path.read_text(encoding="utf-8")
old = '''        for signal in group.to_dict("records"):
            symbol_bars = bars[bars["symbol"].eq(str(signal["symbol"]))].copy()
            if symbol_bars.empty:
                skips.append({"symbol": signal.get("symbol"), "date": str(day), "reason": "MISSING_REPLAY_SYMBOL", "cache_namespace": namespace})
                continue
            is_serclick = str(signal.get("strategy_id")) == "SERCLICK_LEO"
            session_end = session_end_for_strategy(str(signal.get("strategy_id")))
            for bps in slippage_bps:
                priced = reprice_signal_for_slippage(signal, float(bps))
                peak = analyze_same_session_peak(
                    symbol_bars,
                    float(priced["entry_price_slipped"]),
                    priced["entry_timestamp"],
                    str(priced.get("direction", "LONG")),
                    session_end=session_end,
                )
                rules = default_rules_for_signal(priced, serclick=is_serclick)
                replay = replay_signal_grid(symbol_bars, priced, rules, session_end=session_end)
                if replay.empty:
                    continue
                replay["rule_id"] = [rule_family_id(rule) for rule in rules]
                replay["slippage_bps"] = float(bps)
                for key, value in peak.to_dict().items():
                    replay[key] = value
                frames.append(replay)
'''
new = '''        physical_groups: dict[tuple, list[dict]] = {}
        for row_number, signal in enumerate(group.to_dict("records")):
            if str(signal.get("strategy_id")) == "DAN_IRISH":
                # setup_id describes the hypothesis that qualified the trade, not a
                # different physical execution.  Replay identical executions once,
                # then fan the outcome back to every qualifying setup below.
                physical_key = (
                    "DAN_PHYSICAL",
                    str(signal.get("strategy_id")),
                    str(signal.get("variant_id")),
                    str(signal.get("symbol")),
                    str(signal.get("date")),
                    str(pd.Timestamp(signal.get("entry_timestamp"))),
                    str(signal.get("entry_price_raw")),
                    str(signal.get("direction", "LONG")),
                    str(signal.get("stop_reference")),
                )
            else:
                physical_key = ("ROW", int(row_number))
            physical_groups.setdefault(physical_key, []).append(signal)

        for hypotheses in physical_groups.values():
            signal = hypotheses[0]
            symbol_bars = bars[bars["symbol"].eq(str(signal["symbol"]))].copy()
            if symbol_bars.empty:
                skips.append({"symbol": signal.get("symbol"), "date": str(day), "reason": "MISSING_REPLAY_SYMBOL", "cache_namespace": namespace})
                continue
            is_serclick = str(signal.get("strategy_id")) == "SERCLICK_LEO"
            session_end = session_end_for_strategy(str(signal.get("strategy_id")))
            for bps in slippage_bps:
                priced = reprice_signal_for_slippage(signal, float(bps))
                peak = analyze_same_session_peak(
                    symbol_bars,
                    float(priced["entry_price_slipped"]),
                    priced["entry_timestamp"],
                    str(priced.get("direction", "LONG")),
                    session_end=session_end,
                )
                rules = default_rules_for_signal(priced, serclick=is_serclick)
                physical_replay = replay_signal_grid(symbol_bars, priced, rules, session_end=session_end)
                if physical_replay.empty:
                    continue
                physical_replay["rule_id"] = [rule_family_id(rule) for rule in rules]
                physical_replay["slippage_bps"] = float(bps)
                for key, value in peak.to_dict().items():
                    physical_replay[key] = value
                for hypothesis in hypotheses:
                    replay = physical_replay.copy()
                    # Restore hypothesis-specific labels/features while retaining the
                    # slippage-adjusted execution and simulated exit fields.
                    for key, value in hypothesis.items():
                        if key != "entry_price_slipped":
                            replay[key] = value
                    frames.append(replay)
'''
assert old in text, "target replay_signals block not found"
path.write_text(text.replace(old, new, 1), encoding="utf-8")
