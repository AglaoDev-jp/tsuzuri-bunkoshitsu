"""計測ログを日本語で表示する読み取り専用ツール（Python標準ライブラリのみ）。

使い方: python tools/summarize_performance.py [計測ログのパス]
引数を省略すると、このプロジェクトのsrc/logs内の最新ログを読む。
ゲーム本体やOllamaを起動せず、生成データ・設定ファイルを書き換えない。
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
from pathlib import Path
import sys


PURPOSES = {"scene": "場面生成", "summary": "要約", "ending": "追加エンディング",
            "free_story_setup": "自由入力の設定整理"}
ACTIONS = {"game_start": "ゲーム開始", "choice": "選択結果", "continue": "続行ボタン",
           "retry": "直前の選択肢へ", "voice_diagnostic": "音声の固定文計測"}
VOICE_ROLES = {"first_chunk": "表示時の先頭", "next_scene_prefetch": "次場面の先読み",
               "ending_prefetch": "エンディングの先読み",
               "playback_generation": "再生用チャンク", "diagnostic": "固定文診断"}


def format_number(value: object, *, scale: float = 1.0, suffix: str = "") -> str:
    """欠落・不正な統計は0秒と表示せず、「未取得」と区別する。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "未取得"
    try:
        result = value / scale
        return f"{result:.3f}{suffix}" if math.isfinite(result) else "未取得"
    except (OverflowError, ValueError):
        return "未取得"


def summarize(path: Path) -> str:
    """同じtrace_idのイベントをまとめる。途中で終了したログも読み取る。"""
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    skipped = 0
    session = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("trace_id"), str):
                raise ValueError("event expected")
        except (ValueError, TypeError):
            skipped += 1
            continue
        if row.get("action") != "session":
            groups.setdefault(row["trace_id"], []).append(row)
        elif row.get("stage") == "session_info":
            session = row

    lines = [f"計測ログ: {path.name}", "時間は秒。未取得は0秒を意味しません。"]
    if session:
        lines.append(f"アプリ版: {session.get('app_version', '未取得')} / 次場面の音声先読み: "
                     f"{session.get('prefetch_next_scene_first_chunk', '未取得')}")
        if "prefetch_ending_first_chunk" in session:
            lines.append(f"エンディングの音声先読み: {session['prefetch_ending_first_chunk']}")
    for trace_id, rows in groups.items():
        first = rows[0]
        action = ACTIONS.get(first.get("action"), str(first.get("action", "操作")))
        lines += ["", f"[{trace_id}] {action} / モデル: {first.get('model') or '未記録'}"]
        for row in rows:
            if row.get("stage") == "voice_audio":
                role = VOICE_ROLES.get(row.get("voice_role"), "音声")
                if row.get("cache_hit"):
                    lines.append(f"  {role}: キャッシュ再利用")
                else:
                    status = "成功" if row.get("status") == "ok" else "失敗"
                    lines.append(
                        f"  {role}: {status} / {row.get('characters', '?')}文字 / "
                        f"クエリ {format_number(row.get('audio_query_ms'), scale=1000)} / "
                        f"合成HTTP {format_number(row.get('synthesis_ms'), scale=1000)} / "
                        f"保存 {format_number(row.get('cache_write_ms'), scale=1000)}"
                    )
                    lines.append(f"    音声長 {format_number(row.get('audio_seconds'))} / "
                                 f"実時間比 {format_number(row.get('synthesis_rtf'))}")
                    if status == "失敗":
                        lines.append(f"    失敗工程: {row.get('phase', '未取得')} / 例外: {row.get('error_type', '未取得')}")
            elif row.get("stage") in ("voice_generation_started", "voice_prefetch_started"):
                lines.append(f"  音声生成キュー待ち: {format_number(row.get('queue_wait_ms'), scale=1000)}")
            elif row.get("stage") == "voice_diagnostic_environment":
                lines.append(f"  固定文計測: {row.get('source')} / 話者 {row.get('speaker_id')} / "
                             f"エンジン版 {row.get('engine_version') or '未取得'}")
                lines.append("  CPU/GPU稼働モード: 未確認（対応デバイス情報からは判定しません）")
            elif row.get("stage") == "voice_diagnostic_sample":
                label = "最初の試行" if row.get("sample") == 1 else f"繰り返し{row.get('sample')}"
                lines.append(f"  固定文 {label}: {row.get('status')} / 全体 "
                             f"{format_number(row.get('duration_ms'), scale=1000)}")
            elif row.get("stage") == "llm_request":
                purpose = PURPOSES.get(row.get("purpose"), str(row.get("purpose")))
                status = {"ok": "成功", "error": "失敗", "cancelled": "中止"}.get(row.get("status"), "不明")
                lines.append(
                    f"  {purpose} 試行{row.get('attempt', '?')}: {status} / "
                    f"呼出全体 {format_number(row.get('duration_ms'), scale=1000)} / "
                    f"出力速度 {format_number(row.get('eval_tokens_per_second'))} tokens/s"
                )
                lines.append(
                    f"    ロード {format_number(row.get('load_duration_ms'), scale=1000)} / "
                    f"入力処理 {format_number(row.get('prompt_eval_duration_ms'), scale=1000)} / "
                    f"出力生成 {format_number(row.get('eval_duration_ms'), scale=1000)} / "
                    f"出力トークン数 {row.get('eval_count') if row.get('eval_count') is not None else '未取得'}"
                )
                if "server_host" in row:
                    lines.append(
                        f"    接続先 {row.get('server_host')}:{row.get('server_port')} / "
                        f"HTTPとOllama内部時間の差 {format_number(row.get('http_minus_ollama_ms'), scale=1000)}"
                    )
                if row.get("status") != "ok":
                    lines.append(f"    発生工程: {row.get('phase')} / 例外型: {row.get('error_type')}")
            elif row.get("stage") == "summary_applied":
                source = {"prepared": "場面と同時生成", "separate": "従来の別生成",
                          "local_fallback": "通信失敗時の簡易要約"}.get(row.get("source"), "不明")
                lines.append(f"  採用した要約: {source}")
            elif row.get("stage") == "summary_fallback":
                lines.append(f"  要約は従来方式へ: {row.get('reason', '未記録')}")
            elif row.get("stage") == "scene_validation" and row.get("status") != "ok":
                lines.append(f"  場面データ検証: 失敗（試行{row.get('attempt')}）")
            elif row.get("stage") == "first_voice_prepared":
                stale = " / 古い表示の結果" if row.get("stale") else ""
                lines.append(f"  先頭音声準備: {format_number(row.get('duration_ms'), scale=1000)}{stale}")
            elif row.get("stage") == "voice_prefetch_finished":
                target = "エンディング" if row.get("prefetch_kind") == "ending" else "次場面"
                status = {"ready": "準備完了", "error": "失敗・表示時に通常準備",
                          "cancelled": "取消"}.get(row.get("status"), "不明")
                lines.append(
                    f"  {target}の先頭音声を事前準備: {status} / "
                    f"合成・保存 {format_number(row.get('duration_ms'), scale=1000)} / "
                    f"ID {row.get('prefetch_id', '未記録')}"
                )
            elif row.get("stage") == "voice_prefetch_use":
                target = "エンディング" if row.get("prefetch_kind") == "ending" else "次場面"
                status = {"ready": "再利用", "error": "通常準備へ",
                          "cancelled": "取消済み"}.get(row.get("result"), "不明")
                lines.append(
                    f"  事前準備の利用: {status} / "
                    f"残り待ち {format_number(row.get('duration_ms'), scale=1000)} / "
                    f"ID {row.get('prefetch_id', '未記録')} / {target}"
                )
            elif row.get("stage") == "voice_prefetch_cancelled":
                target = "エンディング" if row.get("prefetch_kind") == "ending" else "次場面"
                lines.append(f"  {target}の音声事前準備を取消: ID {row.get('prefetch_id', '未記録')}")
            elif row.get("stage") == "display_started":
                lines.append(f"  本文表示開始まで: {format_number(row.get('elapsed_ms'), scale=1000)}")
            elif row.get("stage") == "typing_completed":
                lines.append(f"  全文表示まで: {format_number(row.get('elapsed_ms'), scale=1000)}")
            elif row.get("stage") == "generation_cancel_requested":
                lines.append(f"  キャンセル要求まで: {format_number(row.get('elapsed_ms'), scale=1000)}")
    if not groups:
        lines.append("まだゲーム操作の記録がありません。")
    if skipped:
        lines.append(f"\n読み取れない行を{skipped}行スキップしました。")
    lines.append("\n注: LLM・音声の内訳は重なる項目を含むため、すべてを足し合わせないでください。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="綴り文庫室の計測ログを日本語で確認します。")
    parser.add_argument("log", nargs="?", type=Path, help="省略時はsrc/logsの最新計測ログ")
    args = parser.parse_args()
    path = args.log
    if path is None:
        log_dir = Path(__file__).resolve().parents[1] / "src" / "logs"
        path = max(log_dir.glob("performance_*.jsonl"), key=lambda p: p.stat().st_mtime, default=None)
    if path is None:
        print("計測ログはまだありません。ゲームを起動して文章を生成してください。")
        return 0
    try:
        print(summarize(path))
        return 0
    except (OSError, UnicodeError) as exc:
        print(f"計測ログを読み取れません: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
