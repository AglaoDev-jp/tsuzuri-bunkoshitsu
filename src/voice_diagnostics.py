"""同じ固定文・話者をゲーム内外で計測。診断WAVはゲーム用と分離する。"""
from __future__ import annotations

from pathlib import Path
import statistics
import tempfile
import threading
from time import perf_counter
from typing import Any

import requests

from performance_monitor import APP_VERSION, DISABLED_MONITOR, PerformanceMonitor, PerformanceTrace
from voicevox_client import VoicevoxClient, VoicevoxError

# 80文字未満の1チャンク。文章を変更した場合はIDも変えて比較の混同を防ぐ。
PROBE_ID = "voice_probe_v1"
PROBE_TEXT = "静かな図書室で、一冊の本を開きました。窓から柔らかな光が差し込み、次の物語が始まります。"


class _RecordingMonitor(PerformanceMonitor):
    """既存計測を転送しつつ、今回の音声1件の数値を結果表示へ取り出す。"""

    def __init__(self, target: PerformanceMonitor) -> None:
        super().__init__()
        self.target = target
        self.audio_rows: list[dict[str, Any]] = []

    def event(self, trace, stage, *, started_at=None, **fields):
        if stage == "voice_audio":
            self.audio_rows.append({**fields, "duration_ms": (
                (perf_counter() - started_at) * 1000 if started_at is not None else None
            )})
        self.target.event(trace, stage, started_at=started_at, **fields)


def engine_information(base_url: str, speaker_id: int) -> dict[str, Any]:
    """任意のGET情報。古いエンジンの404等は未取得にして計測を続ける。

    supported_devicesは対応デバイスであり、稼働モードではない。
    設定変更や、計測前の話者初期化を行って比較条件を変えることはしない。
    """
    result: dict[str, Any] = {"engine_version": None, "supported_devices": None,
                              "speaker_initialized_before": None, "active_device": None,
                              "metadata_errors": {}}
    endpoints = (("engine_version", "/version", None),
                 ("supported_devices", "/supported_devices", None),
                 ("speaker_initialized_before", "/is_initialized_speaker", {"speaker": speaker_id}))
    for key, endpoint, params in endpoints:
        try:
            response = requests.get(base_url.rstrip("/") + endpoint, params=params, timeout=2)
            response.raise_for_status()
            body = response.json()
            if key == "engine_version":
                if not isinstance(body, str) or len(body) > 128:
                    raise ValueError("version format")
            elif key == "supported_devices":
                if not isinstance(body, dict):
                    raise ValueError("devices format")
                body = {k: v for k, v in body.items() if k in ("cpu", "cuda", "dml") and isinstance(v, bool)}
            elif not isinstance(body, bool):
                raise ValueError("initialized format")
            result[key] = body
        except (requests.RequestException, ValueError) as exc:
            result["metadata_errors"][key] = type(exc).__name__
    return result


def run_diagnostic(*, base_url: str, speaker_id: int, samples: int = 3,
                   source: str = "standalone", performance: PerformanceMonitor | None = None,
                   trace: PerformanceTrace | None = None,
                   cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """初回を分離して固定文を合成。毎回別キーでWAVキャッシュの命中を防ぐ。

    エンジンが既に暖まっている場合もあるため、初回をコールド起動とは呼ばない。
    中止は試行の境界で確認。実行中HTTPは既存の30秒/60秒の制限まで待つ場合がある。
    """
    if not 1 <= samples <= 5 or speaker_id < 0:
        raise ValueError("試行数は1〜5、話者IDは0以上で指定してください。")
    monitor = performance or DISABLED_MONITOR
    cancelled = cancel_event or threading.Event()
    report: dict[str, Any] = {"app_version": APP_VERSION, "source": source,
                              "probe_id": PROBE_ID, "speaker_id": speaker_id,
                              "characters": len(PROBE_TEXT), "trials": [], "cancelled": False}
    if cancelled.is_set():
        report["cancelled"] = True
        return report
    report.update(engine_information(base_url, speaker_id))
    monitor.event(trace, "voice_diagnostic_environment", **{k: v for k, v in report.items() if k != "trials"})
    recorder = _RecordingMonitor(monitor)
    with tempfile.TemporaryDirectory(prefix="tsuzuri-voice-diagnostic-") as directory:
        client = VoicevoxClient(base_url=base_url, speaker_id=speaker_id, cache_dir=Path(directory),
                                performance=recorder, performance_trace=trace, voice_role="diagnostic")
        for index in range(1, samples + 1):
            if cancelled.is_set():
                break
            error = None
            try:
                client.create_or_get_audio(PROBE_TEXT, cache_key=f"probe_{index:03d}")
            except VoicevoxError as exc:
                error = type(exc).__name__
            row = {**recorder.audio_rows[-1], "sample": index,
                   "trial_kind": "first_measured" if index == 1 else "repeat",
                   "probe_id": PROBE_ID, "source": source}
            report["trials"].append(row)
            monitor.event(trace, "voice_diagnostic_sample", **row)
            if error is not None:
                # 接続失敗時などに同じ長いタイムアウトを繰り返さない。
                break
    report["cancelled"] = cancelled.is_set()
    return report


def format_report(report: dict[str, Any]) -> str:
    """失敗・未返却を0秒と誤解しない、日本語の診断結果。"""
    def seconds(value):
        return "未取得" if value is None else f"{value / 1000:.3f}秒"
    source = {"game_idle": "ゲーム内（待機中）", "standalone": "単体ツール"}.get(report["source"], report["source"])
    initialized = {True: "はい", False: "いいえ", None: "未取得"}[report.get("speaker_initialized_before")]
    devices = report.get("supported_devices")
    device_text = "未取得" if devices is None else " / ".join(
        f"{key.upper()}: {('対応' if value else '非対応')}" for key, value in devices.items()
    ) or "未取得"
    lines = [f"VOICEVOX音声計測 / {source}",
             f"話者ID: {report['speaker_id']} / 固定文: {report['probe_id']}",
             f"エンジン版: {report.get('engine_version') or '未取得'}",
             f"対応デバイス（稼働モードではありません）: {device_text}",
             "実際のCPU/GPU稼働モード: 未確認",
             f"試行前の話者初期化済み: {initialized}"]
    for row in report["trials"]:
        label = "最初の試行" if row["sample"] == 1 else f"繰り返し{row['sample']}"
        lines.append(f"{label}: {('成功' if row['status'] == 'ok' else '失敗')} / 全体 {seconds(row.get('duration_ms'))}")
        lines.append(f"  クエリ {seconds(row.get('audio_query_ms'))} / 合成HTTP {seconds(row.get('synthesis_ms'))} / 保存 {seconds(row.get('cache_write_ms'))}")
        duration, rtf = row.get("audio_seconds"), row.get("synthesis_rtf")
        lines.append(f"  音声長 {('未取得' if duration is None else f'{duration:.2f}秒')} / 実時間比 {('未取得' if rtf is None else f'{rtf:.3f}')}")
        if row["status"] != "ok":
            lines.append(f"  失敗工程: {row.get('phase')} / 例外: {row.get('error_type')}")
    repeats = [r["synthesis_ms"] for r in report["trials"] if r["sample"] > 1 and r["status"] == "ok" and "synthesis_ms" in r]
    if repeats:
        lines.append(f"2回目以降の合成HTTP中央値: {seconds(statistics.median(repeats))}")
    if report["cancelled"]:
        lines.append("計測を中止しました。実行中だった試行の結果を含む場合があります。")
    lines.append("合成HTTPはエンジン側の待機・処理・転送を含みます。GPU使用や遅延原因は数値だけで断定できません。")
    return "\n".join(lines)
