"""文章を生成せず、ローカル接続先とモデルの対応情報を確認する任意のツール。

ゲーム起動時には実行しない。GET /api/version と、--model指定時のPOST /api/show
だけを使う。モデルのロード・生成・登録変更や、設定ファイルへの書込は行わない。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
from time import perf_counter

import requests


def compare_connections(*, samples: int = 3, timeout: float = 5.0) -> list[dict]:
    """同じ軽量APIを両接続先で測る。ゲームと同じrequestsの通常設定を使用する。

    モデルや物語の生成時間を混ぜず、localhostの名前解決・接続試行等に差が
    現れるかを見るための比較。試行ごとに順番を逆にして片方だけ先にしない。
    """
    targets = ("http://127.0.0.1:11434", "http://localhost:11434")
    results = []
    for index in range(samples):
        for base_url in targets if index % 2 == 0 else targets[::-1]:
            started_at = perf_counter()
            try:
                response = requests.get(base_url + "/api/version", timeout=timeout)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("version"), str):
                    raise ValueError("version field unavailable")
                results.append(dict(base_url=base_url, sample=index + 1, status="ok",
                                    duration_ms=(perf_counter() - started_at) * 1000,
                                    version=body["version"]))
            except (requests.RequestException, ValueError) as exc:
                # 環境変数や接続先情報を含み得る例外本文は、そのまま出力しない。
                results.append(dict(base_url=base_url, sample=index + 1, status="error",
                                    error_type=type(exc).__name__))
    return results


def model_information(base_url: str, model: str, *, timeout: float = 5.0) -> dict:
    """登録済みモデルの情報だけを読む。対応値を推測してAPIへ適用しない。"""
    response = requests.post(base_url.rstrip("/") + "/api/show", json={"model": model}, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("model metadata unavailable")
    # 不要な全メタデータや巨大なテンソル一覧を表示しない。
    return {key: body.get(key) for key in ("capabilities", "thinking", "details", "parameters", "template")}


def main(argv: list[str] | None = None) -> int:
    settings_path = Path(__file__).resolve().parents[1] / "src" / "data" / "game_settings.json"
    default_url = "http://127.0.0.1:11434"
    try:
        default_url = json.loads(settings_path.read_text(encoding="utf-8-sig"))["ollama"]["base_url"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    parser = argparse.ArgumentParser(description="文章生成なしでOllamaの接続・Thinking対応情報を確認します。")
    parser.add_argument("--model", help="任意。登録モデル名を指定すると/api/showも確認")
    parser.add_argument("--base-url", default=default_url, help="モデル情報の確認先。省略時はゲームの設定")
    parser.add_argument("--samples", type=int, choices=range(1, 6), default=3, help="各接続先の試行数（1〜5）")
    parser.add_argument("--show-template", action="store_true", help="モデルの登録テンプレートも表示")
    args = parser.parse_args(argv)

    print("ローカル接続比較（文章生成なし・設定変更なし）")
    rows = compare_connections(samples=args.samples)
    for row in rows:
        if row["status"] == "ok":
            print(f"  {row['base_url']} 試行{row['sample']}: {row['duration_ms']:.1f}ms / Ollama {row['version']}")
        else:
            print(f"  {row['base_url']} 試行{row['sample']}: 接続確認失敗（{row['error_type']}）")
    medians = {}
    for base_url in dict.fromkeys(row["base_url"] for row in rows):
        values = [row["duration_ms"] for row in rows if row["base_url"] == base_url and row["status"] == "ok"]
        if values:
            medians[base_url] = statistics.median(values)
            print(f"  中央値 {base_url}: {medians[base_url]:.1f}ms")
    if len(medians) == 2:
        difference = medians["http://localhost:11434"] - medians["http://127.0.0.1:11434"]
        print(f"  中央値の差（localhost − 127.0.0.1）: {difference:.1f}ms")
    print("注: 軽量APIの比較です。生成時の差や、遅延の原因をこれだけで断定しません。")

    if args.model:
        print(f"\nモデル対応情報: {args.model}")
        try:
            info = model_information(args.base_url, args.model)
        except (requests.RequestException, ValueError) as exc:
            print(f"  情報取得失敗: {type(exc).__name__}")
            return 1
        for key in ("capabilities", "thinking", "details", "parameters"):
            value = info.get(key)
            print(f"  {key}: {json.dumps(value, ensure_ascii=False) if value is not None else '未提供'}")
        if args.show_template:
            print("\n登録テンプレート:")
            print(info.get("template") or "未提供")
        print("Thinking情報が未提供でも、推論が無いとは判断できません。生成設定は変更していません。")
    return 0 if any(row["status"] == "ok" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
