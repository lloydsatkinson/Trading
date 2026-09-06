from __future__ import annotations

import argparse
import json

import scripts.run_strategy_research as research
from scanner.strategies.orb_stocks_in_play.config import ORBConfig
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals


# Frozen A1 historical gate. Float remains point-in-time/UNKNOWN rather than
# being backfilled from a later snapshot, so the historical result does not
# introduce hindsight through current float data.
A1_ORB_CONFIG = ORBConfig(
    min_gap_pct=0.10,
    min_price=1.0,
    max_price=20.0,
)


def _generate_a1_orb_signals(bars, context):
    return generate_orb_signals(bars, context, A1_ORB_CONFIG)


def run_a1(
    root: str = ".",
    feed: str = "sip",
    sessions: int = 60,
    end_date: str | None = None,
    min_n: int = 20,
):
    """Run only the A1 ORB long-pullback variant under the frozen A1 gate."""
    original_generator = research.generate_orb_signals
    research.generate_orb_signals = _generate_a1_orb_signals
    try:
        return research.run_research(
            root=root,
            feed=feed,
            sessions=sessions,
            end_date=end_date,
            strategies=("orb",),
            variants=(research.A1_VARIANT,),
            min_n=min_n,
        )
    finally:
        research.generate_orb_signals = original_generator


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone A1 ORB pullback research")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--sessions", type=int, default=60)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--root", default=".")
    parser.add_argument("--min-n", type=int, default=20)
    args = parser.parse_args()

    result = run_a1(
        root=args.root,
        feed=args.feed,
        sessions=args.sessions,
        end_date=args.end_date,
        min_n=args.min_n,
    )
    print("A1_RESEARCH_DONE", json.dumps({
        "output_dir": str(result.output_dir),
        "signals": len(result.signals),
        "replays": len(result.replays),
        "leaderboard_rows": len(result.leaderboard),
    }))


if __name__ == "__main__":
    main()
