"""
ローカルLLM実行環境「Ollama」と通信するためのモジュール。

このファイルでは、GUIやゲームエンジンが ``requests`` の使い方を
意識しなくて済むように、HTTP通信に関する処理をまとめています。

主な役割
- インストールされているモデルの一覧を取得する
- チャットAPIへJSON形式でリクエストを送る
- 通信エラーやJSON解析エラーを、アプリ用の例外へ変換する

上位のコードでは ``LLMClientError`` だけを扱えばよいため、
HTTP通信の細かい仕組みを知らなくても利用できます。

このように役割を分けておくことで、
ゲーム側は「LLMへ依頼すること」だけに集中できるようになります。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import requests

from performance_monitor import (
    DISABLED_MONITOR, PerformanceMonitor, PerformanceTrace, ollama_statistics,
)


class LLMClientError(RuntimeError):
    """Ollamaとの通信、または返答の解析に失敗したことを表す例外。"""


class LLMGenerationCancelled(LLMClientError):
    """ユーザー操作によって進行中のLLM生成が中止されたことを表す例外。"""


@dataclass(frozen=True)
class OllamaModelInfo:
    """
    Ollamaから取得した1モデル分の表示用情報。

    ``frozen=True`` により生成後の値変更を禁止している。モデル情報は
    読み取り専用データなので、不変にすると意図しない書き換えを防ぎやすい。
    """

    name: str
    size_bytes: int = 0
    parameter_size: str = ""
    quantization_level: str = ""
    family: str = ""

    @property
    def display_name(self) -> str:
        """モデル名と、取得できた補足情報をGUI表示用の1文字列へまとめる。"""
        parts = [self.name]
        details: list[str] = []
        if self.parameter_size:
            details.append(self.parameter_size)
        if self.quantization_level:
            details.append(self.quantization_level)
        if self.size_bytes > 0:
            # Ollamaのsizeはバイト単位。1024の3乗で割ってGiB相当に直す。
            details.append(f"{self.size_bytes / (1024 ** 3):.1f} GB")
        if details:
            parts.append(f"（{' / '.join(details)}）")
        return "".join(parts)


class OllamaClient:
    """
    Ollama APIへアクセスする小さなクライアント。

    インスタンスごとに使用モデルとタイムアウトを持たせることで、
    GUIで選ばれたモデルを、そのゲーム中は一貫して利用できる。
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "gemma3:4b",
        timeout: int = 120,
        performance: PerformanceMonitor | None = None,
    ) -> None:
        """接続先、使用モデル、生成待ち時間を保持する。"""
        # 末尾の「/」を除き、後続の「/api/...」連結で二重スラッシュを防ぐ。
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.performance = performance or DISABLED_MONITOR
        self.performance_trace: PerformanceTrace | None = None
        # 計測にはホスト・ポートだけを残す。URLのユーザー情報やパスは保存しない。
        # 不正URLの扱いは従来どおりHTTP処理へ任せ、診断処理で起動を止めない。
        self._connection_metadata: dict[str, Any] = {}
        try:
            endpoint = urlsplit(self.base_url)
            self._connection_metadata = {"server_host": endpoint.hostname, "server_port": endpoint.port}
        except ValueError:
            pass

        # Tkinter側のキャンセル操作と生成ワーカーは別スレッドで動くため、
        # Eventで中止要求を共有し、Lockで通信中Responseへの参照を保護する。
        # stream=TrueでResponseを保持すると、close()により待機中の接続を閉じ、
        # 完了済みの古い結果が画面へ戻るまで待たずに中止を通知できる。
        self._cancel_event = threading.Event()
        self._response_lock = threading.Lock()
        self._active_response: requests.Response | None = None

    def cancel_current_request(self) -> None:
        """
        進行中の生成へ中止を通知し、保持中のHTTPレスポンスを閉じる。

        接続開始前に押された場合もEventは残るため、その後ワーカーが
        ``generate_json()`` へ到達した時点で通信せず安全に中止される。
        """
        self._cancel_event.set()
        with self._response_lock:
            response = self._active_response

        if response is not None:
            response.close()

    def list_models(self) -> list[OllamaModelInfo]:
        """
        Ollamaに登録されているモデルを取得し、表示用データへ変換する。

        一覧取得は画面起動時にも行うため、生成処理より短い5秒の
        タイムアウトを使い、Ollama未起動時に長く待たせない。
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            # 4xx/5xxを例外へ変換し、正常レスポンスだけを後段へ渡す。
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise LLMClientError(
                "Ollamaに接続できません。Ollamaが起動しているか確認してください。"
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMClientError("Ollamaのモデル一覧を読み取れませんでした。") from exc

        models: list[OllamaModelInfo] = []
        seen: set[str] = set()
        for item in data.get("models", []):
            # Ollamaのバージョン差を考慮し、nameとmodelの両候補を見る。
            name = str(item.get("name") or item.get("model") or "").strip()
            # 空名と重複はコンボボックスへ表示しない。
            if not name or name in seen:
                continue
            seen.add(name)
            details = item.get("details") or {}
            models.append(
                OllamaModelInfo(
                    name=name,
                    size_bytes=int(item.get("size") or 0),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization_level=str(
                        details.get("quantization_level") or ""
                    ),
                    family=str(details.get("family") or ""),
                )
            )
        return models

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        think: bool = False,
        temperature: float = 0.7,
        purpose: str = "unspecified",
        scene_number: int | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """従来の生成を計測する薄い入口。purpose等はAPIへ送信しない。

        Thinking・JSON・コンテキスト長などの生成条件は従来と同一に保つ。
        応答に統計がないモデルでも、HTTP所要時間と文字数だけで利用できる。
        """
        with self.performance.measure(
            self.performance_trace, "llm_request", purpose=purpose,
            scene_number=scene_number, attempt=attempt,
            system_characters=len(system_prompt), user_characters=len(user_prompt),
            think_requested=think, temperature=temperature, stream=False,
            output_format="json", timeout_seconds=self.timeout,
            num_ctx_requested=None, num_predict_requested=None, phase="preflight",
            **self._connection_metadata,
        ) as measurement:
            return self._generate_json_impl(
                system_prompt=system_prompt, user_prompt=user_prompt,
                think=think, temperature=temperature, measurement=measurement,
            )

    def _generate_json_impl(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        think: bool = False,
        temperature: float = 0.7,
        measurement: dict[str, Any],
    ) -> dict[str, Any]:
        """
        チャットAPIへ問い合わせ、AIが返したJSONオブジェクトを返す。

        Ollama API全体のレスポンスもJSONだが、欲しいゲームデータはさらに
        ``message.content`` 内のJSON文字列として入っている。そのため、
        ここでは「HTTPレスポンス」と「AI本文」の2段階でJSONを解析する。

        Args:
            system_prompt: AIの役割と共通ルール。
            user_prompt: 今回生成してほしい具体的な内容。
            think: 対応モデルの思考モードを使うかどうか。
            temperature: 低いほど安定的、高いほど表現が多様になりやすい。
        """

        if self._cancel_event.is_set():
            raise LLMGenerationCancelled("物語の生成がキャンセルされました。")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # format=jsonで、Ollama側にもJSON出力を要求する。
            "format": "json",
            # 逐次受信ではなく、完成した1レスポンスをまとめて受け取る。
            "stream": False,
            # 対応モデルでは思考表示を抑制でき、応答時間短縮にもつながる。
            "think": think,
            "options": {
                "temperature": temperature,
            },
        }

        response: requests.Response | None = None
        try:
            # APIへは従来どおり完成JSONを1件だけ要求する。一方requests側は
            # stream=Trueとして本文の受信前にResponseを保持し、画面の
            # キャンセル操作から接続を閉じられるようにする。
            measurement["phase"] = "http"
            http_started_at = perf_counter()
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
                stream=True,
            )

            measurement["headers_wait_ms"] = (perf_counter() - http_started_at) * 1000
            measurement["http_status"] = response.status_code
            with self._response_lock:
                if self._cancel_event.is_set():
                    response.close()
                    raise LLMGenerationCancelled(
                        "物語の生成がキャンセルされました。"
                    )
                self._active_response = response

            response.raise_for_status()
            # .json()も内部で.contentを読む。先に受信を完了させることで、
            # 本文の待機と外側JSONの解析を分離する（APIのstream設定は変更しない）。
            response.content
            measurement["http_ms"] = (perf_counter() - http_started_at) * 1000
            measurement["phase"] = "outer_json"
            parse_started_at = perf_counter()
            try:
                body = response.json()
            finally:
                measurement["outer_json_ms"] = (perf_counter() - parse_started_at) * 1000
            # 任意の統計項目の欠落・異常は、正常なゲームデータを拒否する理由にしない。
            try:
                measurement.update(ollama_statistics(body))
                api_total_ms = measurement.get("total_duration_ms")
                if isinstance(api_total_ms, (int, float)):
                    # HTTPの時間範囲とOllama内部の時間範囲の差。接続時間そのものとは
                    # 断定しない。接続先比較の前後で同じ方法で確認できるように残す。
                    measurement["http_minus_ollama_ms"] = measurement["http_ms"] - api_total_ms
            except Exception:
                measurement["statistics_unavailable"] = True
        except LLMGenerationCancelled:
            raise
        except requests.exceptions.ConnectionError as exc:
            if self._cancel_event.is_set():
                raise LLMGenerationCancelled(
                    "物語の生成がキャンセルされました。"
                ) from exc
            raise LLMClientError(
                "Ollamaに接続できません。Ollamaを起動してから再試行してください。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            if self._cancel_event.is_set():
                raise LLMGenerationCancelled(
                    "物語の生成がキャンセルされました。"
                ) from exc
            raise LLMClientError(
                "Ollamaの応答がタイムアウトしました。軽いモデルを試してください。"
            ) from exc
        except requests.RequestException as exc:
            if self._cancel_event.is_set():
                raise LLMGenerationCancelled(
                    "物語の生成がキャンセルされました。"
                ) from exc
            raise LLMClientError(f"Ollama通信エラー: {exc}") from exc
        except json.JSONDecodeError as exc:
            if self._cancel_event.is_set():
                raise LLMGenerationCancelled(
                    "物語の生成がキャンセルされました。"
                ) from exc
            raise LLMClientError("Ollamaの返答をJSONとして読めませんでした。") from exc
        finally:
            if response is not None:
                with self._response_lock:
                    if self._active_response is response:
                        self._active_response = None
                response.close()

        # 本文受信完了とボタン操作がほぼ同時だった場合も、解析済みの古い結果を
        # 正常終了として上位へ返さず、キャンセルとして統一して扱う。
        if self._cancel_event.is_set():
            raise LLMGenerationCancelled("物語の生成がキャンセルされました。")

        # 2回目のJSON解析対象となる、AIの発言本文だけを取り出す。
        measurement["phase"] = "content"
        content = body.get("message", {}).get("content", "")
        if not content:
            raise LLMClientError("Ollamaから空の返答が返りました。")

        measurement["phase"] = "content_json"
        parse_started_at = perf_counter()
        try:
            # format=jsonを指定しても、content自体は文字列なので明示的に解析する。
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                "AIの返答が正しいJSON形式ではありませんでした。"
            ) from exc
        finally:
            measurement["content_json_ms"] = (perf_counter() - parse_started_at) * 1000

        # ゲーム側はキー名で値を取得するため、配列などは受け付けない。
        if not isinstance(parsed, dict):
            raise LLMClientError("AIの返答JSONがオブジェクト形式ではありません。")
        measurement["phase"] = "complete"
        return parsed
