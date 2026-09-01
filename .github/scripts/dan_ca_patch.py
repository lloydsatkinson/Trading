from pathlib import Path

path = Path("scanner/multistrategy/study.py")
text = path.read_text(encoding="utf-8")

if "corporate_actions_process30" not in text:
    old = '''        digest = hashlib.sha1("\\n".join(symbols).encode("utf-8")).hexdigest()[:12]
        cache = self.paths.cache / "corporate_actions" / f"{sessions[0]}_{sessions[-1]}_{digest}.csv"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            out = pd.read_csv(cache)
            if "action_date" in out.columns:
                out["action_date"] = pd.to_datetime(out["action_date"], errors="coerce").dt.date
            self._corporate_action_audit_status = "OK_CACHE"
            return out

        try:
            parts = [
                self.api.corporate_actions(
                    batch,
                    start=str(sessions[0]),
                    end=str(sessions[-1]),
                    types=("reverse_split", "forward_split", "unit_split"),
                    limit=1_000,
                )
                for batch in _chunks(symbols, self.cfg.symbol_batch_size)
            ]
'''
    new = '''        digest = hashlib.sha1("\\n".join(symbols).encode("utf-8")).hexdigest()[:12]
        # Alpaca filters this endpoint by process_date, while our replay audit is
        # keyed to the action/ex-date. Buffer the query so actions processed just
        # outside the study window cannot be missed at the boundary.
        process_buffer_days = 30
        query_start = sessions[0] - timedelta(days=process_buffer_days)
        query_end = sessions[-1] + timedelta(days=process_buffer_days)
        cache = self.paths.cache / "corporate_actions" / (
            f"corporate_actions_process30_{query_start}_{query_end}_{digest}.csv"
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            out = pd.read_csv(cache)
            if "action_date" in out.columns:
                out["action_date"] = pd.to_datetime(out["action_date"], errors="coerce").dt.date
            self._corporate_action_audit_status = "OK"
            self._corporate_action_audit_error = None
            return out

        try:
            parts = [
                self.api.corporate_actions(
                    batch,
                    start=str(query_start),
                    end=str(query_end),
                    types=("reverse_split", "forward_split", "unit_split"),
                    limit=1_000,
                )
                for batch in _chunks(symbols, self.cfg.symbol_batch_size)
            ]
'''
    assert old in text
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
