"""モデルに依存しない計測専用の記録処理。ゲームの判断・生成条件は変更しない。

時刻の差は時計合わせの影響を受けない perf_counter() で測定し、日時は照合用に
併記する。プロンプト・物語・推論の本文は保存せず、長さと数値だけを記録する。
ログ保存に失敗しても、物語生成や画面進行の成功・失敗には影響させない。
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import threading
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4

APP_VERSION = "3.1.5"


@dataclass(frozen=True)
class PerformanceTrace:
    """1回の操作を識別する。ワーカーにも同じ値を渡し、古い操作と混ぜない。"""

    trace_id: str
    started_at: float
    action: str
    model: str


class PerformanceMonitor:
    """UTF-8のJSON Linesを、スレッド間で行が混ざらないように追記する。"""

    def __init__(self, log_dir: Path | None = None, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        # 1起動につき1ファイル。秒単位で同時起動してもUUIDで衝突を避ける。
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        self.path = None if log_dir is None else Path(log_dir) / f"performance_{session_id}.jsonl"
        self.write_failed = False

    def start(self, action: str, *, model: str = "", **fields: Any) -> PerformanceTrace:
        """操作開始点を確定する。モデル名で分岐しないためGemma/LLM-jp等で共通。"""
        trace = PerformanceTrace(uuid4().hex[:12], perf_counter(), action, model)
        self.event(trace, "operation_started", **fields)
        return trace

    def event(
        self,
        trace: PerformanceTrace | None,
        stage: str,
        *,
        started_at: float | None = None,
        **fields: Any,
    ) -> None:
        """保存前に計測を確定する。入出力の遅延や保存失敗を計測対象へ足さない。"""
        if not self.enabled or self.path is None or trace is None or self.write_failed:
            return
        try:
            now = perf_counter()
            row = {
                "schema_version": 1,
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "trace_id": trace.trace_id,
                "action": trace.action,
                "model": trace.model,
                "stage": stage,
                "elapsed_ms": round((now - trace.started_at) * 1000, 3),
                **fields,
            }
            if started_at is not None:
                row["duration_ms"] = round((now - started_at) * 1000, 3)
            line = json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(line)
        except Exception:
            # 権限・ディスク容量・JSON変換などの問題を、ゲーム本体へ伝播させない。
            # 毎イベントで同じ保存失敗を繰り返さないよう、この起動の計測だけ停止。
            self.write_failed = True

    @contextmanager
    def measure(
        self, trace: PerformanceTrace | None, stage: str, **fields: Any
    ) -> Iterator[dict[str, Any]]:
        """成功・失敗のどちらでも所要時間を残し、元の例外はそのまま伝える。"""
        started_at = perf_counter()
        details = dict(fields)
        status = "ok"
        try:
            yield details
        except BaseException as exc:
            status = "cancelled" if type(exc).__name__ == "LLMGenerationCancelled" else "error"
            # 例外文に生成本文や接続先が含まれる場合があるため、型名だけを残す。
            details["error_type"] = type(exc).__name__
            raise
        finally:
            self.event(trace, stage, started_at=started_at, status=status, **details)


# 計測なしでも従来どおりクライアントを単体利用できるようにする。
DISABLED_MONITOR = PerformanceMonitor()


def ollama_statistics(body: object) -> dict[str, Any]:
    """任意のAPI応答から安全に統計を拾う。欠落値を0と誤認しない。

    Gemma 4・LLM-jp・旧Ollamaなどで返却項目が異なっても、項目がなければNone。
    eval_countはAPIの値をそのまま使い、推論/最終回答トークンへ独自に分割しない。
    """
    if not isinstance(body, dict):
        return {}

    def number(key: str) -> int | float | None:
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            return value if value >= 0 and math.isfinite(value) else None
        except (OverflowError, ValueError):
            return None

    fields: dict[str, Any] = {}
    for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
        value = number(key)
        fields[key + "_ms"] = None if value is None else value / 1_000_000
    for key in ("prompt_eval_count", "eval_count", "prompt_eval_cached_count"):
        fields[key] = number(key)
    for prefix in ("prompt_eval", "eval"):
        count, duration = number(prefix + "_count"), number(prefix + "_duration")
        # 0秒、未返却、非数値のときは速度を捏造せずNoneにする。
        rate = None
        try:
            if count is not None and duration is not None and duration > 0:
                candidate = count * 1_000_000_000 / duration
                rate = candidate if math.isfinite(candidate) else None
        except (OverflowError, ZeroDivisionError):
            pass
        fields[prefix + "_tokens_per_second"] = rate
    reason = body.get("done_reason")
    fields["done_reason"] = reason if isinstance(reason, str) and len(reason) <= 64 else None
    fields["done"] = body.get("done") if isinstance(body.get("done"), bool) else None
    message = body.get("message")
    if isinstance(message, dict):
        for key in ("content", "thinking"):
            text = message.get(key)
            # 「未返却」と「返却された空文字」を区別する。
            fields[key + "_characters"] = len(text) if isinstance(text, str) else None
    return fields
