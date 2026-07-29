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
from typing import Any

import requests


class LLMClientError(RuntimeError):
    """Ollamaとの通信、または返答の解析に失敗したことを表す例外。"""


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
        base_url: str = "http://localhost:11434",
        model: str = "gemma3:4b",
        timeout: int = 120,
    ) -> None:
        """接続先、使用モデル、生成待ち時間を保持する。"""
        # 末尾の「/」を除き、後続の「/api/...」連結で二重スラッシュを防ぐ。
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

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

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            # 1回目のJSON解析: Ollama APIレスポンス全体。
            body = response.json()
        except requests.exceptions.ConnectionError as exc:
            raise LLMClientError(
                "Ollamaに接続できません。Ollamaを起動してから再試行してください。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LLMClientError(
                "Ollamaの応答がタイムアウトしました。軽いモデルを試してください。"
            ) from exc
        except requests.RequestException as exc:
            raise LLMClientError(f"Ollama通信エラー: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMClientError("Ollamaの返答をJSONとして読めませんでした。") from exc

        # 2回目のJSON解析対象となる、AIの発言本文だけを取り出す。
        content = body.get("message", {}).get("content", "")
        if not content:
            raise LLMClientError("Ollamaから空の返答が返りました。")

        try:
            # format=jsonを指定しても、content自体は文字列なので明示的に解析する。
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError(
                "AIの返答が正しいJSON形式ではありませんでした。"
            ) from exc

        # ゲーム側はキー名で値を取得するため、配列などは受け付けない。
        if not isinstance(parsed, dict):
            raise LLMClientError("AIの返答JSONがオブジェクト形式ではありません。")
        return parsed
