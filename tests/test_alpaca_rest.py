from datetime import datetime, timezone

from scanner.serclick.alpaca_rest import AlpacaCredentials, AlpacaRest


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = __import__('json').dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=60):
        self.calls.append((url, dict(params or {})))
        symbols = (params or {}).get("symbols", "")
        if "P027445" in symbols:
            return FakeResponse(400, {"message": "invalid symbol: P027445"})
        return FakeResponse(200, {"bars": {"AAPL": [{"t": "2026-08-27T04:00:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 12345, "n": 100, "vw": 100.2}]}, "next_page_token": None})


def test_stock_bars_skips_invalid_symbol_and_keeps_valid_symbols(monkeypatch):
    api = AlpacaRest(AlpacaCredentials("key", "secret"), pause_seconds=0)
    api.session = FakeSession()
    monkeypatch.setattr("scanner.serclick.alpaca_rest.time.sleep", lambda *_: None)
    df = api.stock_bars(["AAPL", "P027445"], "1Day", datetime(2026, 8, 20, tzinfo=timezone.utc), datetime(2026, 8, 28, tzinfo=timezone.utc), feed="sip")
    assert list(df["symbol"]) == ["AAPL"]
    assert len(api.session.calls) == 2
    assert api.session.calls[0][1]["symbols"] == "AAPL,P027445"
    assert api.session.calls[1][1]["symbols"] == "AAPL"


def test_corporate_actions_flattens_split_events_and_paginates(monkeypatch):
    api = AlpacaRest(AlpacaCredentials("key", "secret"), pause_seconds=0)
    calls = []

    def fake_get(url, params=None):
        params = dict(params or {})
        calls.append((url, params))
        if not params.get("page_token"):
            return {
                "corporate_actions": {
                    "reverse_splits": [{
                        "id": "rs1",
                        "symbol": "AAA",
                        "ex_date": "2026-08-31",
                        "old_rate": 10,
                        "new_rate": 1,
                    }]
                },
                "next_page_token": "page-2",
            }
        return {
            "corporate_actions": {
                "forward_splits": [{
                    "id": "fs1",
                    "symbol": "BBB",
                    "ex_date": "2026-09-01",
                    "old_rate": 1,
                    "new_rate": 2,
                }]
            },
            "next_page_token": None,
        }

    monkeypatch.setattr(api, "_get", fake_get)
    out = api.corporate_actions(
        ["AAA", "BBB"],
        start="2026-08-28",
        end="2026-09-02",
        types=("reverse_split", "forward_split"),
    )

    assert len(calls) == 2
    assert calls[0][0].endswith("/v1/corporate-actions")
    assert calls[0][1]["symbols"] == "AAA,BBB"
    assert calls[0][1]["types"] == "reverse_split,forward_split"
    assert calls[1][1]["page_token"] == "page-2"
    assert set(out["action_type"]) == {"reverse_split", "forward_split"}
    assert set(out["action_date"].astype(str)) == {"2026-08-31", "2026-09-01"}


def test_credentials_load_project_root_dotenv_when_shell_vars_missing(monkeypatch, tmp_path):
    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY", "APCA_API_BASE_URL", "ALPACA_DATA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    fake_module = tmp_path / "scanner" / "serclick" / "alpaca_rest.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("# placeholder", encoding="utf-8")
    (tmp_path / ".env").write_text("APCA_API_KEY_ID=test_key_from_dotenv\nAPCA_API_SECRET_KEY=test_secret_from_dotenv\nAPCA_API_BASE_URL=https://paper-api.alpaca.markets\n", encoding="utf-8")
    import scanner.serclick.alpaca_rest as module
    monkeypatch.setattr(module, "__file__", str(fake_module))
    creds = AlpacaCredentials.from_env()
    assert creds.key == "test_key_from_dotenv"
    assert creds.secret == "test_secret_from_dotenv"
    assert creds.trading_base == "https://paper-api.alpaca.markets"
