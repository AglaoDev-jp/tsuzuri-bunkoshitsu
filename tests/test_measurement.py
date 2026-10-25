"""実モデルを呼ばず、API互換性・分岐・計測失敗時の継続を確認する。

実行: プロジェクト直下で python -m unittest discover -s tests -v
Gemma/LLM-jpの品質や実機速度を模擬するテストではない。
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests
from game_engine import GameDataError, GameEngine
from llm_client import LLMClientError, LLMGenerationCancelled, OllamaClient
from performance_monitor import PerformanceMonitor, ollama_statistics
from voicevox_client import VoicevoxClient, VoicevoxError


def response(data, *, status=200):
    """requests本体のResponseを使い、.content/.json()の実際の挙動も通す。"""
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(data, ensure_ascii=False).encode("utf-8")
    value.encoding = "utf-8"
    return value


def scene_data(correct, *, final=False):
    """両分岐と正解位置の契約を満たす、短い確定済みの場面。"""
    data = dict(title="約束", scene_text="手紙を届ける。", choice_a="渡す", choice_b="待つ",
                correct_choice=correct, bad_end_title="すれ違い", bad_end_text="届かなかった。",
                background_tag="room", bgm_tag="calm")
    data.update(dict(good_end_title="帰還", good_end_text="無事に帰った。") if final
                else dict(correct_result="手紙が届いた。"))
    return data


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.monitor = PerformanceMonitor(Path(self.directory.name), enabled=True)
        self.client = OllamaClient(model="gemma4:test", performance=self.monitor)
        self.client.performance_trace = self.monitor.start("test", model=self.client.model)

    def rows(self):
        return [json.loads(line) for line in self.monitor.path.read_text(encoding="utf-8").splitlines()]

    def test_payload_unchanged_for_gemma_and_llm_jp(self):
        # モデルによって特別なthink/num_ctx等を注入しないことが重要。
        for model in ("gemma4:e4b", "gemma4:latest", "llm-jp-4.1-direct:latest"):
            with self.subTest(model=model):
                self.client.model = model
                self.client.performance_trace = self.monitor.start("test", model=model)
                body = {"message": {"content": '{"ok":true}', "thinking": "非公開の推論"},
                        "total_duration": 2_000_000_000, "load_duration": 50_000_000,
                        "prompt_eval_count": 100, "prompt_eval_duration": 100_000_000,
                        "eval_count": 80, "eval_duration": 1_000_000_000,
                        "done": True, "done_reason": "stop"}
                with patch("llm_client.requests.post", return_value=response(body)) as post:
                    self.assertEqual(self.client.generate_json(
                        system_prompt="秘密の指示", user_prompt="秘密の物語", purpose="scene", attempt=2,
                    ), {"ok": True})
                self.assertEqual(post.call_count, 1)
                self.assertEqual(post.call_args.kwargs, {
                    "json": {"model": model, "messages": [
                        {"role": "system", "content": "秘密の指示"},
                        {"role": "user", "content": "秘密の物語"}],
                        "format": "json", "stream": False, "think": False,
                        "options": {"temperature": 0.7}},
                    "timeout": 120, "stream": True,
                })
        row = self.rows()[-1]
        self.assertEqual(row["eval_tokens_per_second"], 80)
        self.assertEqual(row["attempt"], 2)
        self.assertEqual(row["thinking_characters"], len("非公開の推論"))
        text = self.monitor.path.read_text(encoding="utf-8")
        for secret in ("非公開の推論", "秘密の指示", "秘密の物語"):
            self.assertNotIn(secret, text)

    def test_missing_statistics_are_not_zero(self):
        with patch("llm_client.requests.post", return_value=response({"message": {"content": '{"a":1}'}})):
            self.assertEqual(self.client.generate_json(system_prompt="s", user_prompt="u"), {"a": 1})
        row = self.rows()[-1]
        self.assertIsNone(row["eval_count"])
        self.assertIsNone(row["thinking_characters"])
        self.assertIsNone(row["eval_tokens_per_second"])

    def test_unusual_statistics_do_not_break_valid_content(self):
        for duration in (None, 0, -1, "unknown", True, float("nan"), float("inf"), 10**1000, 1e-320):
            with self.subTest(duration=str(duration)[:20]):
                stats = ollama_statistics({"eval_count": 10, "eval_duration": duration})
                json.dumps(stats, allow_nan=False)
        with patch("llm_client.requests.post", return_value=response({"message": {"content": '{"ok":1}'}})):
            with patch("llm_client.ollama_statistics", side_effect=ValueError("bad metrics")):
                self.assertEqual(self.client.generate_json(system_prompt="s", user_prompt="u"), {"ok": 1})

    def test_invalid_json_and_empty_content_record_failure(self):
        for content, phase in (("", "content"), ("not json", "content_json"), ("[]", "content_json")):
            with self.subTest(content=content):
                with patch("llm_client.requests.post", return_value=response({"message": {"content": content}})):
                    with self.assertRaises(LLMClientError):
                        self.client.generate_json(system_prompt="s", user_prompt="u")
                self.assertEqual(self.rows()[-1]["status"], "error")
                self.assertEqual(self.rows()[-1]["phase"], phase)

    def test_timeout_and_cancellation_preserve_exceptions(self):
        with patch("llm_client.requests.post", side_effect=requests.exceptions.Timeout):
            with self.assertRaises(LLMClientError):
                self.client.generate_json(system_prompt="s", user_prompt="u")
        self.assertEqual(self.rows()[-1]["status"], "error")
        self.client.cancel_current_request()
        with patch("llm_client.requests.post") as post:
            with self.assertRaises(LLMGenerationCancelled):
                self.client.generate_json(system_prompt="s", user_prompt="u")
            post.assert_not_called()
        self.assertEqual(self.rows()[-1]["status"], "cancelled")

    def test_log_write_failure_does_not_break_generation(self):
        # フォルダを作れない状況を実際に作る。モデルの返答は正常に返る必要がある。
        blocked = Path(self.directory.name) / "not_a_directory"
        blocked.write_text("x")
        self.monitor.path = blocked / "performance.jsonl"
        with patch("llm_client.requests.post", return_value=response({"message": {"content": '{"ok":1}'}})):
            self.assertEqual(self.client.generate_json(system_prompt="s", user_prompt="u"), {"ok": 1})
        self.assertTrue(self.monitor.write_failed)

    def test_disabled_logging_creates_no_file(self):
        monitor = PerformanceMonitor(Path(self.directory.name) / "disabled", enabled=False)
        trace = monitor.start("test")
        with monitor.measure(trace, "sample"):
            pass
        self.assertFalse(monitor.path.exists())

    def test_parallel_records_are_valid_and_isolated(self):
        def write(index):
            trace = self.monitor.start("parallel", model=str(index))
            for _ in range(20):
                self.monitor.event(trace, "sample")
        threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rows = [r for r in self.rows() if r["action"] == "parallel"]
        self.assertEqual(len(rows), 84)
        self.assertEqual(len({r["trace_id"] for r in rows}), 4)

    def test_legacy_responses_use_ten_calls_with_fallback(self):
        engine = GameEngine(llm_client=self.client, genre_name="手紙", genre_prompt="手紙を届ける")
        pattern = ["a", "b", "a", "b", "a"]
        bodies = [scene_data(pattern[0])]
        for i in range(1, 5):
            bodies += [{"summary": "手紙を届ける旅を続ける。"}, scene_data(pattern[i], final=i == 4)]
        bodies += [{"epilogue": "日常へ戻った。", "clear_message": "クリア。", "ai_comment": "無事に届いた。"}]
        with patch.object(engine, "_create_answer_pattern", return_value=pattern):
            with patch("llm_client.requests.post", side_effect=[response({"message": {
                "content": json.dumps(b, ensure_ascii=False)}}) for b in bodies]) as post:
                first = engine.start()
                # 不正解と再挑戦ではAPIを使わず、場面も正解位置も変わらない。
                self.assertEqual(engine.choose("b")["status"], "bad_end")
                self.assertIs(engine.retry_current_scene(), first)
                self.assertEqual(post.call_count, 1)
                for i, choice in enumerate(pattern):
                    result = engine.choose(choice)
                    self.assertEqual(result["status"], "good_end" if i == 4 else "next_scene")
                self.assertEqual(post.call_count, 10)
        requests_log = [r for r in self.rows() if r["stage"] == "llm_request"]
        self.assertEqual([r["purpose"] for r in requests_log],
                         ["scene", "summary", "scene", "summary", "scene", "summary", "scene", "summary", "scene", "ending"])

    def test_scene_validation_retries_keep_same_limit(self):
        engine = GameEngine(llm_client=self.client, genre_name="手紙", genre_prompt="手紙")
        invalid = scene_data("b")
        valid = scene_data("a")
        with patch.object(engine, "_create_answer_pattern", return_value=["a"] * 5):
            with patch("llm_client.requests.post", side_effect=[response({"message": {
                "content": json.dumps(b)}}) for b in (invalid, valid)]) as post:
                self.assertEqual(engine.start().correct_choice, "a")
                self.assertEqual(post.call_count, 2)
        events = [r for r in self.rows() if r["stage"] == "scene_validation"]
        self.assertEqual([r["status"] for r in events], ["error", "ok"])

    def test_summary_and_ending_fallbacks_still_continue(self):
        engine = GameEngine(llm_client=self.client, genre_name="手紙", genre_prompt="手紙")
        engine.scene_number = 1
        engine.answer_pattern = ["a"] * 5
        engine.current_scene = engine._parse_scene(scene_data("a"), "a")
        with patch("llm_client.requests.post", side_effect=[requests.exceptions.Timeout,
                   response({"message": {"content": json.dumps(scene_data("a"))}})]) as post:
            self.assertEqual(engine.choose("a")["status"], "next_scene")
            self.assertEqual(post.call_count, 2)
        self.assertTrue(engine.story_summary)
        engine.scene_number = 5
        engine.current_scene = engine._parse_scene(scene_data("a", final=True), "a")
        with patch("llm_client.requests.post", side_effect=requests.exceptions.Timeout):
            result = engine.choose("a")
        self.assertEqual(result["status"], "good_end")
        self.assertTrue(result["epilogue"])

    def test_voice_cache_reuses_audio_without_more_requests(self):
        voice = VoicevoxClient(cache_dir=Path(self.directory.name) / "voice",
                               performance=self.monitor, performance_trace=self.client.performance_trace)
        query = response({"accent_phrases": []})
        synthesis = response({})
        synthesis._content = b"RIFF-test-audio"
        with patch("voicevox_client.requests.post", side_effect=[query, synthesis]) as post:
            first = voice.create_or_get_audio("手紙。", cache_key="scene_1_001")
            second = voice.create_or_get_audio("手紙。", cache_key="scene_1_001")
            self.assertEqual(first, second)
            self.assertEqual(post.call_count, 2)
        audio = [r for r in self.rows() if r["stage"] == "voice_audio"]
        self.assertEqual([r["cache_hit"] for r in audio], [False, True])
        self.assertIn("synthesis_ms", audio[0])
        self.assertNotIn("手紙", self.monitor.path.read_text(encoding="utf-8"))

    def test_voice_error_still_raises_original_type(self):
        voice = VoicevoxClient(cache_dir=Path(self.directory.name) / "voice",
                               performance=self.monitor, performance_trace=self.client.performance_trace)
        with patch("voicevox_client.requests.post", side_effect=requests.exceptions.Timeout):
            with self.assertRaises(VoicevoxError):
                voice.create_or_get_audio("文章。", cache_key="scene_1")
        self.assertEqual(self.rows()[-1]["status"], "error")

    def test_free_story_setup_keeps_two_requests_at_start(self):
        engine = GameEngine(llm_client=self.client, genre_name="自由に綴る", genre_prompt="手紙")
        setup = {"genre_name": "手紙", "genre_prompt": "手紙を届ける物語", "background_tag": "room", "bgm_tag": "calm"}
        with patch.object(engine, "_create_answer_pattern", return_value=["a"] * 5):
            with patch("llm_client.requests.post", side_effect=[response({"message": {
                "content": json.dumps(b)}}) for b in (setup, scene_data("a"))]) as post:
                engine.prepare_free_story("手紙を届けたい")
                engine.start()
                self.assertEqual(post.call_count, 2)
        self.assertIn("手紙を届けたい", engine.genre_prompt)
        rows = [r for r in self.rows() if r["stage"] == "llm_request"]
        self.assertEqual([r["purpose"] for r in rows], ["free_story_setup", "scene"])


class PresentationTests(unittest.TestCase):
    """Tkの実画面は作らず、既存の表示待ち・世代ガードを実メソッドで確認する。"""

    def setUp(self):
        import main
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = main.AdventureApp.__new__(main.AdventureApp)
        app = self.app
        app.performance = PerformanceMonitor(Path(self.directory.name), enabled=True)
        app.performance_trace = app.performance.start("test", model="gemma4:latest")
        app.presentation_id = 0
        app.voice_enabled_var = Mock()
        app.voice_enabled_var.get.return_value = False
        app.speaker_var = Mock()
        app.speaker_var.get.return_value = "3"
        app.voice_pipeline = Mock()
        app.bgm_manager = Mock()
        # afterは予約だけ行い、テスト内で実行してワーカーとGUIの境界を再現する。
        app.root = Mock()
        self.callbacks = []
        app.root.after.side_effect = lambda delay, callback: self.callbacks.append(callback)
        for name in ("_cancel_typing", "_disable_choice", "_stop_waiting_animation",
                     "_show_background", "_show_result_image", "_clear_text_area", "_write",
                     "_start_typing", "_append_backlog"):
            setattr(app, name, Mock())

    def prepare(self):
        self.app._prepare_narrative(display_text="場面本文", voice_parts=[("読み上げ", "scene_1")],
                                    background_tag="room", bgm_tag="calm")

    def rows(self):
        return [json.loads(line) for line in self.app.performance.path.read_text(encoding="utf-8").splitlines()]

    def test_voice_off_displays_without_preparation(self):
        self.prepare()
        self.app._start_typing.assert_called_once()
        self.app.voice_pipeline.prepare_first_chunk.assert_not_called()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.assertIn("display_started", [r["stage"] for r in self.rows()])

    def test_voice_on_waits_then_starts_display_and_audio(self):
        self.app.voice_enabled_var.get.return_value = True
        # 実際のスレッド数は変更せず、ここだけstart()で即実行する代替を使う。
        def thread_factory(*, target, args, **kwargs):
            return Mock(start=lambda: target(*args))
        with patch("main.threading.Thread", side_effect=thread_factory):
            self.prepare()
        self.app.voice_pipeline.prepare_first_chunk.assert_called_once()
        self.app._start_typing.assert_not_called()
        self.assertEqual(len(self.callbacks), 1)
        self.callbacks.pop()()
        self.app._start_typing.assert_called_once()
        self.app.voice_pipeline.speak_sequence.assert_called_once()
        stages = [r["stage"] for r in self.rows()]
        self.assertLess(stages.index("first_voice_prepared"), stages.index("display_started"))

    def test_voice_failure_falls_back_to_text(self):
        self.app.voice_enabled_var.get.return_value = True
        self.app.voice_pipeline.prepare_first_chunk.side_effect = VoicevoxError("音声失敗")
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.prepare()
        self.callbacks.pop()()
        self.app._start_typing.assert_called_once()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.assertEqual(next(r for r in self.rows() if r["stage"] == "first_voice_prepared")["status"], "error")

    def test_stale_voice_result_does_not_display(self):
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.prepare()
        self.app.presentation_id += 1
        self.callbacks.pop()()
        self.app._start_typing.assert_not_called()
        self.app.voice_pipeline.speak_sequence.assert_not_called()

    def test_stale_generation_does_not_restore_game(self):
        self.app.generation_active = False
        self.app.generation_id = 2
        self.app.engine = None
        self.assertFalse(self.app._complete_generation(1, Mock()))

    def test_successful_start_is_not_logged_as_error(self):
        self.app._complete_generation = Mock(return_value=True)
        self.app._show_story_text_area = Mock()
        self.app._show_scene = Mock()
        scene = Mock()
        self.app._finish_start_generation(scene, Mock(), 1)
        self.app._show_scene.assert_called_once_with(scene)
        self.assertNotIn("generation_error", [r["stage"] for r in self.rows()])

    def test_choice_readiness_guard_is_unchanged(self):
        app = self.app
        app.choice_a_button, app.choice_b_button = Mock(), Mock()
        app.engine = Mock(finished=False)
        app.choice_buttons_ready = True
        app.typing_active = False
        app.busy = True
        app._enable_choice()
        app.choice_a_button.config.assert_not_called()
        app.busy = False
        app._enable_choice()
        app.choice_a_button.config.assert_called_once()
        self.assertEqual(self.rows()[-1]["stage"], "choices_enabled")


class SummaryToolTests(unittest.TestCase):
    def test_missing_statistics_and_truncated_line_are_readable(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from summarize_performance import summarize
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "performance.jsonl"
            rows = [dict(trace_id="a", action="game_start", model="gemma4:latest", stage="llm_request",
                         purpose="scene", status="ok", attempt=1, duration_ms=1234, eval_count=None),
                    dict(trace_id="a", action="game_start", stage="display_started", elapsed_ms=1500)]
            path.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"truncated"', encoding="utf-8")
            before = path.read_bytes()
            output = summarize(path)
            self.assertIn("場面生成", output)
            self.assertIn("未取得", output)
            self.assertIn("1.500", output)
            self.assertIn("1行スキップ", output)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
