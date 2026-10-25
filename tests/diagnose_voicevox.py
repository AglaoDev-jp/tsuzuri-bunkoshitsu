"""ゲームと同じ固定文・同じ音声クライアントで、単体の合成時間を測る。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
from performance_monitor import PerformanceMonitor
from voice_diagnostics import format_report, run_diagnostic


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    settings = json.loads((root / "src/data/game_settings.json").read_text(encoding="utf-8-sig"))
    parser = argparse.ArgumentParser(
        description="固定文を合成してVOICEVOXの時間を計測します。音声は再生しません。", add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="使い方を表示して終了")
    parser._optionals.title = "オプション"
    parser.add_argument("--speaker", type=int, default=settings["voicevox"]["speaker_id"], help="ゲーム画面と同じ話者IDを指定")
    parser.add_argument("--base-url", default=settings["voicevox"]["base_url"], help="省略時はゲームと同じ接続先")
    parser.add_argument("--samples", type=int, choices=range(1, 6), default=3, help="試行数（1〜5、既定3）")
    args = parser.parse_args(argv)
    if args.speaker < 0:
        parser.error("話者IDは0以上で指定してください。")
    monitor = PerformanceMonitor(root / "src/logs", enabled=True)
    trace = monitor.start("voice_diagnostic", source="standalone")
    print(f"固定文を合成しています（{args.samples}回）。中止はCtrl+C。", flush=True)
    try:
        report = run_diagnostic(base_url=args.base_url, speaker_id=args.speaker,
                                samples=args.samples, source="standalone", performance=monitor, trace=trace)
    except KeyboardInterrupt:
        print("計測を中止しました。完了済みの試行はログに残ります。")
        return 130
    print(format_report(report))
    print(f"計測ログ: {monitor.path}" if not monitor.write_failed else "計測ログを保存できませんでした。")
    return 0 if report["trials"] and all(r["status"] == "ok" for r in report["trials"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
