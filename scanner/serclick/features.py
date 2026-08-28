from __future__ import annotations

from collections import defaultdict, deque
from datetime import time
from math import isfinite

import numpy as np
import pandas as pd

from .config import SerClickConfig

ET = "America/New_York"


def _bar_dollar(df: pd.DataFrame) -> pd.Series:
    px = df["vwap"].where(df["vwap"].notna() & (df["vwap"] > 0), (df["high"] + df["low"] + df["close"]) / 3.0)
    return df["volume"].fillna(0.0) * px.fillna(df["close"])


def prepare_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True)
    out["timestamp"] = ts
    out["timestamp_et"] = ts.dt.tz_convert(ET)
    out["date"] = out["timestamp_et"].dt.date
    out["tod"] = out["timestamp_et"].dt.time
    out["bar_dollar"] = _bar_dollar(out)
    return out


def classify_early_day(early: pd.DataFrame, prior_close: float, cfg: SerClickConfig) -> dict:
    if early.empty or not prior_close or prior_close <= 0:
        return {}
    x = prepare_bars(early).sort_values("timestamp")
    pm = x[x["tod"] < time(9, 30)]
    open30 = x[(x["tod"] >= time(9, 30)) & (x["tod"] < time(10, 0))]
    through_10 = x[x["tod"] < time(10, 0)]

    pm_high = float(pm["high"].max()) if not pm.empty else np.nan
    pm_dollar = float(pm["bar_dollar"].sum()) if not pm.empty else 0.0
    pm_volume = float(pm["volume"].sum()) if not pm.empty else 0.0
    pm_vwap = pm_dollar / pm_volume if pm_volume > 0 else np.nan

    hod10 = float(through_10["high"].max()) if not through_10.empty else np.nan
    open30_dollar = float(open30["bar_dollar"].sum()) if not open30.empty else 0.0
    open30_volume = float(open30["volume"].sum()) if not open30.empty else 0.0
    open30_vwap = open30_dollar / open30_volume if open30_volume > 0 else np.nan

    pm_extension = pm_high / prior_close if np.isfinite(pm_high) else np.nan
    hod10_extension = hod10 / prior_close if np.isfinite(hod10) else np.nan

    leo_pm = bool(np.isfinite(pm_extension) and pm_extension > cfg.extension_ratio and pm_dollar > cfg.pm_dollar_turnover_min)
    leo_open = bool(np.isfinite(hod10_extension) and hod10_extension > cfg.extension_ratio and open30_dollar > cfg.open30_dollar_turnover_min)
    extension_runner = bool(
        (np.isfinite(pm_extension) and pm_extension > cfg.extension_ratio)
        or (np.isfinite(hod10_extension) and hod10_extension > cfg.extension_ratio)
    )
    if leo_pm and leo_open:
        population = "BOTH"
    elif leo_pm:
        population = "LEO_PM"
    elif leo_open:
        population = "LEO_OPEN"
    elif extension_runner:
        population = "NEITHER_CONTROL"
    else:
        population = "NOT_RUNNER"

    pm_extension_runner = bool(np.isfinite(pm_extension) and pm_extension > cfg.extension_ratio)
    if leo_pm:
        discovery_time = "09:30"
    elif leo_open:
        discovery_time = "10:00"
    elif extension_runner:
        discovery_time = "09:30" if pm_extension_runner else "10:00"
    else:
        discovery_time = None

    return {
        "prior_close": float(prior_close),
        "pm_high": pm_high,
        "pm_extension": pm_extension,
        "pm_volume": pm_volume,
        "pm_vwap": pm_vwap,
        "pm_dollar_turnover": pm_dollar,
        "hod_1000": hod10,
        "hod_1000_extension": hod10_extension,
        "open30_volume": open30_volume,
        "open30_vwap": open30_vwap,
        "open30_dollar_turnover": open30_dollar,
        "leo_pm_pass": leo_pm,
        "leo_open_pass": leo_open,
        "extension_runner": extension_runner,
        "population": population,
        "discovery_time": discovery_time,
    }


def online_percentile(history: deque[float], value: float) -> float:
    vals = [x for x in history if isfinite(x)]
    if len(vals) < 10 or not isfinite(value):
        return np.nan
    a = np.asarray(vals, dtype=float)
    return float(np.mean(a <= value))


def _time_window(df: pd.DataFrame, end_i: int, minutes: int) -> pd.DataFrame:
    end_ts = df.iloc[end_i]["timestamp_et"]
    start_ts = end_ts - pd.Timedelta(minutes=minutes)
    return df[(df["timestamp_et"] > start_ts) & (df["timestamp_et"] <= end_ts)]


def _mark_at_or_after(df: pd.DataFrame, target: pd.Timestamp, tolerance_min: int) -> float:
    y = df[(df["timestamp_et"] >= target) & (df["timestamp_et"] <= target + pd.Timedelta(minutes=tolerance_min))]
    if y.empty:
        return np.nan
    return float(y.iloc[0]["close"])


def analyze_candidate_day(bars: pd.DataFrame, qualification: dict, cfg: SerClickConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if bars.empty:
        return pd.DataFrame(), pd.DataFrame()

    x = prepare_bars(bars).sort_values("timestamp").reset_index(drop=True)
    x = x[(x["tod"] >= time(4, 0)) & (x["tod"] < time(20, 0))].reset_index(drop=True)
    if x.empty:
        return pd.DataFrame(), pd.DataFrame()

    symbol = str(x.iloc[0]["symbol"])
    day = x.iloc[0]["date"]
    if not (x["tod"] >= time(9, 30)).any():
        return pd.DataFrame(), pd.DataFrame()

    session_dollar = 0.0
    session_volume = 0.0
    running_hod = -np.inf
    fade_dollar = 0.0
    fade_volume = 0.0
    fade_price_bins: defaultdict[float, float] = defaultdict(float)
    fade_bin_width = None
    shorts_seen = False
    absorption_seen_ts: pd.Timestamp | None = None
    armed_seen = False
    ignition_seen = False
    abs_hist: deque[float] = deque(maxlen=240)
    exp_hist: deque[float] = deque(maxlen=240)
    transitions: list[dict] = []
    events: list[dict] = []

    discovery_hm = qualification.get("discovery_time") or "10:00"
    dh, dm = [int(v) for v in discovery_hm.split(":")]
    discovery_ts = pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=dh, minute=dm, tz=ET)
    transitions.append({"symbol": symbol, "date": str(day), "timestamp": str(discovery_ts), "state": "DISCOVERED", "reason": qualification.get("population", "UNKNOWN")})

    prev_close_bar = np.nan
    for i, row in x.iterrows():
        tod = row["tod"]
        ts = row["timestamp_et"]
        if tod < time(9, 30):
            prev_close_bar = float(row["close"])
            continue

        bar_dollar = float(row["bar_dollar"] or 0.0)
        volume = float(row["volume"] or 0.0)
        session_dollar += bar_dollar
        session_volume += volume
        session_vwap = session_dollar / session_volume if session_volume > 0 else np.nan
        high, close, low = float(row["high"]), float(row["close"]), float(row["low"])

        if high > running_hod:
            running_hod = high
            fade_dollar = 0.0
            fade_volume = 0.0
            fade_price_bins.clear()
            fade_bin_width = max(0.01, running_hod * 0.005)
        else:
            fade_dollar += bar_dollar
            fade_volume += volume
            px = float(row["vwap"]) if pd.notna(row["vwap"]) and row["vwap"] > 0 else (high + low + close) / 3.0
            if fade_bin_width:
                bucket = round(px / fade_bin_width) * fade_bin_width
                fade_price_bins[bucket] += volume

        fade_vwap = fade_dollar / fade_volume if fade_volume > 0 else np.nan
        fade_hvn = max(fade_price_bins, key=fade_price_bins.get) if fade_price_bins else np.nan
        drawdown = (close / running_hod - 1.0) if running_hod > 0 else np.nan
        eligible_now = ts >= discovery_ts

        if eligible_now and (not shorts_seen) and np.isfinite(drawdown) and drawdown <= -cfg.shorts_building_drawdown:
            shorts_seen = True
            transitions.append({"symbol": symbol, "date": str(day), "timestamp": str(ts), "state": "SHORTS_BUILDING", "reason": f"drawdown_from_hod={drawdown:.4f}", "running_hod": running_hod, "drawdown_from_hod": drawdown, "session_vwap": session_vwap, "fade_vwap": fade_vwap})

        w = _time_window(x, i, cfg.absorption_window_minutes)
        w = w[w["tod"] >= time(9, 30)]
        abs_raw = abs_pct = down_fraction = new_low_extension = np.nan
        down_dollar = 0.0
        if len(w) >= 3:
            wc = w.copy()
            wc["prev_close"] = wc["close"].shift(1)
            wc["is_down"] = wc["close"] < wc["prev_close"]
            total_dollar = float(wc["bar_dollar"].sum())
            down_dollar = float(wc.loc[wc["is_down"], "bar_dollar"].sum())
            down_fraction = down_dollar / total_dollar if total_dollar > 0 else np.nan
            start_px = float(wc.iloc[0]["close"])
            window_low = float(wc["low"].min())
            downside_disp = max(0.0, (start_px - window_low) / start_px) if start_px > 0 else np.nan
            abs_raw = (down_dollar / 1_000_000.0) / max(downside_disp, 0.002) if np.isfinite(downside_disp) else np.nan
            abs_pct = online_percentile(abs_hist, abs_raw)
            p = x[(x["timestamp_et"] > ts - pd.Timedelta(minutes=cfg.absorption_window_minutes * 3)) & (x["timestamp_et"] <= ts - pd.Timedelta(minutes=cfg.absorption_window_minutes)) & (x["tod"] >= time(9, 30))]
            if not p.empty:
                prior_low = float(p["low"].min())
                new_low_extension = max(0.0, (prior_low - window_low) / prior_low) if prior_low > 0 else np.nan
            else:
                new_low_extension = 0.0
            if np.isfinite(abs_raw):
                abs_hist.append(abs_raw)
            abs_signal = bool(eligible_now and shorts_seen and np.isfinite(abs_pct) and abs_pct >= cfg.absorption_percentile and np.isfinite(down_fraction) and down_fraction >= cfg.absorption_min_down_fraction and down_dollar >= cfg.absorption_min_down_dollar and np.isfinite(new_low_extension) and new_low_extension <= cfg.absorption_max_new_low_extension)
            if abs_signal and (absorption_seen_ts is None or ts - absorption_seen_ts > pd.Timedelta(minutes=cfg.absorption_window_minutes)):
                absorption_seen_ts = ts
                transitions.append({"symbol": symbol, "date": str(day), "timestamp": str(ts), "state": "ABSORPTION", "reason": "heavy down-dollar with little new-low progress", "absorption_raw": abs_raw, "absorption_percentile": abs_pct, "down_fraction": down_fraction, "down_dollar": down_dollar, "new_low_extension": new_low_extension, "fade_vwap": fade_vwap})

        ew = _time_window(x, i, cfg.expansion_window_minutes)
        ew = ew[ew["tod"] >= time(9, 30)]
        exp_raw = exp_pct = up_disp = ret3 = np.nan
        buy_dollar = 0.0
        if len(ew) >= 2:
            ec = ew.copy()
            ec["prev_close"] = ec["close"].shift(1)
            ec["is_up"] = ec["close"] > ec["prev_close"]
            buy_dollar = float(ec.loc[ec["is_up"], "bar_dollar"].sum())
            base = float(ec["low"].min())
            up_disp = max(0.0, (close - base) / base) if base > 0 else np.nan
            exp_raw = up_disp / max(buy_dollar / 1_000_000.0, 0.05) if np.isfinite(up_disp) else np.nan
            exp_pct = online_percentile(exp_hist, exp_raw)
            if np.isfinite(exp_raw):
                exp_hist.append(exp_raw)
            r3w = _time_window(x, i, 3)
            if len(r3w) >= 2:
                base3 = float(r3w.iloc[0]["close"])
                ret3 = close / base3 - 1.0 if base3 > 0 else np.nan

        expansion_signal = bool(np.isfinite(exp_pct) and exp_pct >= cfg.expansion_percentile and np.isfinite(up_disp) and up_disp >= cfg.expansion_min_up_displacement and buy_dollar >= cfg.expansion_min_buy_dollar and np.isfinite(ret3) and ret3 >= cfg.acceleration_min_return_3m)
        absorption_recent = bool(absorption_seen_ts is not None and ts - absorption_seen_ts <= pd.Timedelta(minutes=cfg.absorption_memory_minutes))
        pain = fade_vwap

        if absorption_recent and np.isfinite(pain) and close <= pain and (pain - close) / pain <= cfg.armed_distance_to_pain and not armed_seen:
            armed_seen = True
            transitions.append({"symbol": symbol, "date": str(day), "timestamp": str(ts), "state": "ARMED", "reason": "within 3% of fade-VWAP pain level after absorption", "pain_level": pain, "session_vwap": session_vwap, "fade_hvn": fade_hvn})

        crossed_pain = bool(np.isfinite(pain) and np.isfinite(prev_close_bar) and prev_close_bar <= pain and close > pain)
        if eligible_now and crossed_pain:
            qualifies_ignition = bool(shorts_seen and absorption_recent and expansion_signal)
            event_type = "IGNITION" if qualifies_ignition else "PAIN_RECLAIM"
            events.append({"symbol": symbol, "date": str(day), "timestamp": ts, "event_type": event_type, "population": qualification.get("population"), "leo_pm_pass": qualification.get("leo_pm_pass"), "leo_open_pass": qualification.get("leo_open_pass"), "pain_level": pain, "fade_vwap": fade_vwap, "session_vwap": session_vwap, "fade_hvn": fade_hvn, "absorption_percentile": abs_pct, "expansion_percentile": exp_pct, "drawdown_from_hod": drawdown, "ret3": ret3, "signal_close": close})
            if qualifies_ignition and not ignition_seen:
                ignition_seen = True
                transitions.append({"symbol": symbol, "date": str(day), "timestamp": str(ts), "state": "IGNITION", "reason": "pain reclaim + recent absorption + expansion", "pain_level": pain, "absorption_percentile": abs_pct, "expansion_percentile": exp_pct})
        prev_close_bar = close

    trans_df = pd.DataFrame(transitions)
    event_df = pd.DataFrame(events)
    if event_df.empty:
        return trans_df, event_df

    rows = []
    for _, e in event_df.iterrows():
        signal_ts = pd.Timestamp(e["timestamp"])
        future = x[x["timestamp_et"] > signal_ts]
        if future.empty:
            continue
        next_bar = future.iloc[0]
        raw_entry = float(next_bar["open"])
        entry = raw_entry * (1.0 + cfg.slippage_bps / 10_000.0)
        entry_ts = next_bar["timestamp_et"]
        out = e.to_dict()
        out["entry_timestamp"] = entry_ts
        out["entry_raw_open"] = raw_entry
        out["entry_price_slipped"] = entry
        if entry_ts.time() < time(10, 30):
            out["ignition_window"] = "09:30-10:30"
        elif entry_ts.time() < time(15, 0):
            out["ignition_window"] = "10:30-15:00"
        elif entry_ts.time() < time(16, 0):
            out["ignition_window"] = "15:00-16:00"
        else:
            out["ignition_window"] = "16:00-20:00"
        for mins in cfg.forward_minutes:
            mark = _mark_at_or_after(x, entry_ts + pd.Timedelta(minutes=mins), cfg.mark_tolerance_minutes)
            out[f"ret_{mins}m"] = mark / entry - 1.0 if np.isfinite(mark) and entry > 0 else np.nan
        horizon = x[(x["timestamp_et"] >= entry_ts) & (x["tod"] < time(20, 0))]
        if not horizon.empty:
            out["mfe_to_2000"] = float(horizon["high"].max()) / entry - 1.0
            out["mae_to_2000"] = float(horizon["low"].min()) / entry - 1.0
            imax = horizon["high"].astype(float).idxmax()
            out["time_to_mfe_min"] = (x.loc[imax, "timestamp_et"] - entry_ts).total_seconds() / 60.0
            out["ret_to_2000"] = float(horizon.iloc[-1]["close"]) / entry - 1.0
        else:
            out["mfe_to_2000"] = out["mae_to_2000"] = out["time_to_mfe_min"] = out["ret_to_2000"] = np.nan
        rth = x[(x["timestamp_et"] >= entry_ts) & (x["tod"] < time(16, 0))]
        out["ret_to_1600"] = float(rth.iloc[-1]["close"]) / entry - 1.0 if not rth.empty else np.nan
        rows.append(out)
    return trans_df, pd.DataFrame(rows)
