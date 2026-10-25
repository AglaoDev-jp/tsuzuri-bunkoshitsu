"""同時要約の採用時点・互換性・呼び出し回数を実モデルなしで確認する。"""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from game_engine import GameEngine
from game_prompts import build_scene_prompt
from llm_client import LLMGenerationCancelled, OllamaClient
from performance_monitor import PerformanceMonitor
from test_measurement import response, scene_data
import diagnose_ollama


class SummaryInSceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.monitor = PerformanceMonitor(Path(self.directory.name), enabled=True)
        self.client = OllamaClient(performance=self.monitor)
        self.client.performance_trace = self.monitor.start("test", model="gemma4:12b")

    def engine(self, **kwargs):
        return GameEngine(llm_client=self.client, genre_name="手紙", genre_prompt="手紙を届ける", **kwargs)

    def rows(self):
        return [json.loads(line) for line in self.monitor.path.read_text(encoding="utf-8").splitlines()]

    def test_five_scenes_use_six_calls_for_both_models(self):
        # モデル名による分岐を入れず、同じプロトコルと分岐動作を確認する。
        for model in ("gemma4:12b", "llm-jp-4.1-direct:latest"):
            with self.subTest(model=model):
                self.client.model = model
                self.client.performance_trace = self.monitor.start("test", model=model)
                engine = self.engine()
                pattern = ["a", "b", "a", "b", "a"]
                scenes = [scene_data(pattern[i], final=i == 4) for i in range(5)]
                for i in range(4):
                    scenes[i]["summary_after_correct"] = f"主人公は手紙の届け先に向け、場面{i+1}の課題を解決した。"
                bodies = scenes + [dict(epilogue="日常へ。", clear_message="クリア。", ai_comment="届いた。")]
                with patch.object(engine, "_create_answer_pattern", return_value=pattern):
                    with patch("llm_client.requests.post", side_effect=[response({"message": {
                        "content": json.dumps(body, ensure_ascii=False)}}) for body in bodies]) as post:
                        first = engine.start()
                        self.assertEqual(engine.story_summary, "")
                        self.assertEqual(engine.choose("b")["status"], "bad_end")
                        self.assertEqual(engine.story_summary, "")
                        self.assertIs(engine.retry_current_scene(), first)
                        self.assertEqual(post.call_count, 1)
                        for i, choice in enumerate(pattern):
                            result = engine.choose(choice)
                            self.assertEqual(result["status"], "good_end" if i == 4 else "next_scene")
                            if i < 4:
                                self.assertEqual(engine.story_summary, scenes[i]["summary_after_correct"])
                        self.assertEqual(post.call_count, 6)
                        for call in post.call_args_list:
                            self.assertEqual(call.args[0], "http://127.0.0.1:11434/api/chat")
                            payload = call.kwargs["json"]
                            self.assertEqual(payload["model"], model)
                            self.assertIs(payload["think"], False)
                            self.assertIs(payload["stream"], False)
                        prompts = [c.kwargs["json"]["messages"][1]["content"] for c in post.call_args_list]
                        self.assertTrue(all("summary_after_correct" in text for text in prompts[:4]))
                        self.assertNotIn("summary_after_correct", prompts[4])
                applied = [r for r in self.rows() if r["trace_id"] == self.client.performance_trace.trace_id
                           and r["stage"] == "summary_applied"]
                self.assertEqual([r["source"] for r in applied], ["prepared"] * 4)

    def test_missing_invalid_or_long_summary_does_not_retry_scene(self):
        for prepared in (None, {}, [], False, 12, "", "   ", "あ" * 101):
            with self.subTest(prepared=prepared):
                engine = self.engine()
                first = scene_data("a")
                first["summary_after_correct"] = prepared
                second = scene_data("b")
                second["summary_after_correct"] = "次の正解後の要約。"
                bodies = [first, {"summary": "従来方式で更新した記憶。"}, second]
                with patch.object(engine, "_create_answer_pattern", return_value=["a", "b", "a", "b", "a"]):
                    with patch("llm_client.requests.post", side_effect=[response({"message": {
                        "content": json.dumps(b)}}) for b in bodies]) as post:
                        engine.start()
                        self.assertEqual(post.call_count, 1)
                        self.assertEqual(engine.choose("a")["status"], "next_scene")
                        self.assertEqual(post.call_count, 3)
                self.assertEqual(engine.story_summary, "従来方式で更新した記憶。")

    def test_summary_limit_and_whitespace(self):
        engine = self.engine(summary_max_characters=20)
        self.assertEqual(engine._prepared_summary("\n主人公は  手紙を届けた。\t")[0], "主人公は 手紙を届けた。")
        self.assertTrue(engine._prepared_summary("あ" * 20)[0])
        self.assertEqual(engine._prepared_summary("あ" * 21), ("", "over_limit"))

    def test_disabled_mode_ignores_prepared_summary(self):
        engine = self.engine(summary_in_scene=False)
        first = scene_data("a")
        first["summary_after_correct"] = "使ってはいけない事前要約。"
        bodies = [first, {"summary": "別生成した正しい記憶。"}, scene_data("b")]
        with patch.object(engine, "_create_answer_pattern", return_value=["a", "b", "a", "b", "a"]):
            with patch("llm_client.requests.post", side_effect=[response({"message": {
                "content": json.dumps(b)}}) for b in bodies]) as post:
                self.assertEqual(engine.start().summary_after_correct, "")
                engine.choose("a")
                self.assertEqual(post.call_count, 3)
                self.assertNotIn("summary_after_correct", post.call_args_list[0].kwargs["json"]["messages"][1]["content"])
        self.assertEqual(engine.story_summary, "別生成した正しい記憶。")

    def test_cancel_during_next_scene_is_not_retried_or_swallowed(self):
        engine = self.engine()
        first = scene_data("a")
        first["summary_after_correct"] = "正解後の記憶。"
        with patch.object(engine, "_create_answer_pattern", return_value=["a"] * 5):
            with patch("llm_client.requests.post", return_value=response({"message": {"content": json.dumps(first)}})):
                engine.start()
        with patch("llm_client.requests.post", side_effect=LLMGenerationCancelled("中止")) as post:
            with self.assertRaises(LLMGenerationCancelled):
                engine.choose("a")
            self.assertEqual(post.call_count, 1)

    def test_final_scene_ignores_unused_summary(self):
        engine = self.engine(total_scenes=1)
        data = scene_data("a", final=True)
        data["summary_after_correct"] = "不要な記憶。"
        with patch.object(engine, "_create_answer_pattern", return_value=["a"]):
            with patch("llm_client.requests.post", return_value=response({"message": {"content": json.dumps(data)}})):
                scene = engine.start()
        self.assertEqual(scene.summary_after_correct, "")

    def test_prompt_only_adds_internal_summary_in_enabled_mode(self):
        kwargs = dict(genre_name="手紙", genre_prompt="手紙を届ける", scene_number=2,
                      total_scenes=5, story_summary="主人公は駅へ来た。", required_correct_choice="b")
        legacy = build_scene_prompt(**kwargs)
        combined = build_scene_prompt(**kwargs, include_summary=True, summary_max_characters=75)
        self.assertNotIn("summary_after_correct", legacy)
        self.assertIn("75文字以内", combined)
        self.assertIn("主人公は駅へ来た。", combined)
        self.assertIn("correct_choiceは必ず b", combined)

    def test_connection_metrics_do_not_change_custom_endpoint(self):
        client = OllamaClient(base_url="http://example.invalid:14000", performance=self.monitor)
        client.performance_trace = self.client.performance_trace
        with patch("llm_client.requests.post", return_value=response({"message": {"content": '{"ok":true}'},
                                                                   "total_duration": 1000})) as post:
            client.generate_json(system_prompt="s", user_prompt="u")
        self.assertEqual(post.call_args.args[0], "http://example.invalid:14000/api/chat")
        row = self.rows()[-1]
        self.assertEqual(row["server_host"], "example.invalid")
        self.assertEqual(row["server_port"], 14000)
        self.assertIsInstance(row["http_minus_ollama_ms"], float)


class ConnectionDiagnosticTests(unittest.TestCase):
    def test_diagnostic_only_checks_version_and_show(self):
        with patch("diagnose_ollama.requests.get", return_value=response({"version": "test"})) as get:
            with patch("diagnose_ollama.requests.post", return_value=response({"capabilities": ["completion"],
                       "thinking": {"values": [False]}, "template": "登録テンプレート"})) as post:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code = diagnose_ollama.main(["--model", "llm-jp-4.1-direct:latest", "--samples", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(get.call_count, 4)
        self.assertTrue(all(c.args[0].endswith("/api/version") for c in get.call_args_list))
        self.assertTrue(post.call_args.args[0].endswith("/api/show"))
        self.assertEqual(post.call_args.kwargs["json"], {"model": "llm-jp-4.1-direct:latest"})
        self.assertNotIn("登録テンプレート", output.getvalue())

    def test_missing_thinking_metadata_does_not_mean_no_thinking(self):
        with patch("diagnose_ollama.requests.post", return_value=response({"capabilities": ["completion"]})):
            info = diagnose_ollama.model_information("http://127.0.0.1:11434", "gemma4:12b")
        self.assertIsNone(info["thinking"])


if __name__ == "__main__":
    unittest.main()
