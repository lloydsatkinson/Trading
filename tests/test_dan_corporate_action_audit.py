from datetime import date, timedelta

import pandas as pd

from scanner.multistrategy.study import MultiStrategyStudy


class _FakeCorporateApi:
    def __init__(self):
        self.calls = []

    def corporate_actions(self, symbols, start, end, types, limit=1000):
        self.calls.append({
            "symbols": list(symbols),
            "start": str(start),
            "end": str(end),
            "types": tuple(types),
            "limit": int(limit),
        })
        return pd.DataFrame([{
            "symbol": "AAA",
            "action_type": "reverse_split",
            "action_date": date(2026, 8, 31),
        }])


def test_corporate_action_query_buffers_process_date_around_study_window(tmp_path):
    study = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=2)
    fake = _FakeCorporateApi()
    study._api = fake
    sessions = [date(2026, 8, 28), date(2026, 8, 31)]

    study._corporate_actions(["AAA"], sessions)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert date.fromisoformat(call["start"]) <= sessions[0] - timedelta(days=30)
    assert date.fromisoformat(call["end"]) >= sessions[-1] + timedelta(days=30)


def test_cached_corporate_action_audit_remains_ok_for_selection(tmp_path):
    sessions = [date(2026, 8, 28), date(2026, 8, 31)]
    first = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=2)
    first._api = _FakeCorporateApi()
    first._corporate_actions(["AAA"], sessions)
    assert first._corporate_action_audit_status == "OK"

    second = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=2)
    second._api = _FakeCorporateApi()
    cached = second._corporate_actions(["AAA"], sessions)

    assert not cached.empty
    assert second._corporate_action_audit_status == "OK"
    assert second._api.calls == []
