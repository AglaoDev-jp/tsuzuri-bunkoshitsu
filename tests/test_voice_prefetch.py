"""実HTTP・実音声を使わず、先読みと遷移・停止の競合を確認する。

Eventで処理の順番を制御するため、通信時間やsleepに依存しない。
"""

import json
from pathlib import Path
import tempfile
import threading
import unittest
import sys
from unittest.mock import Mock, patch

import test_measurement as baseline
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from game_engine import Scene
from performance_monitor import PerformanceMonitor
from voicevox_client import VoicePipeline, VoicevoxClient


def audio_response():
    value = baseline.response({})
    value._content = b"RIFF-test-audio"
    return value


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / "cache"
        self.monitor = PerformanceMonitor(Path(self.directory.name) / "logs", enabled=True)
        self.trace = self.monitor.start("choice", model="gemma4:12b")
        # 実際の常駐スレッドは必要なテストでだけ起動する。pygameの再生はしない。
        with patch("voicevox_client.threading.Thread.start"):
            self.pipeline = VoicePipeline(base_url="http://voice.test", cache_dir=self.cache,
                                          on_error=Mock())
        self.threads = []
        self.releases = []
        self.failures = []

    def tearDown(self):
        for event in self.releases:
            event.set()
        self.pipeline.shutdown()
        for thread in self.threads:
            thread.join(3)
            self.assertFalse(thread.is_alive(), "音声ワーカーが停止しません")
        self.assertEqual(self.failures, [])

    def start(self, action):
        def run():
            try:
                action()
            except BaseException as exc:
                self.failures.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def queue(self, text="次の場面です。", speaker=3):
        self.pipeline.prefetch_first_chunk([(text, "scene_2")], speaker_id=speaker,
                                           performance=self.monitor, performance_trace=self.trace)
        return self.pipeline._first_chunk_prefetch

    def prepare(self, text="次の場面です。", speaker=3):
        return self.pipeline.prepare_first_chunk([(text, "scene_2")], speaker_id=speaker,
                                                performance=self.monitor, performance_trace=self.trace)

    def rows(self):
        return [json.loads(line) for line in self.monitor.path.read_text(encoding="utf-8").splitlines()]

    def blocked_http(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def post(url, **kwargs):
            if url.endswith("/audio_query"):
                return baseline.response({})
            entered.set()
            if not release.wait(3):
                raise AssertionError("合成の待機を解除できません")
            return audio_response()
        return entered, release, post

    def test_fifo_after_current_chunks_and_no_prefetch_playback(self):
        played = []
        self.pipeline._put_playback_job = lambda job: played.append(job)
        # 80文字を超える次場面でも先読みは1チャンクだけ。現在文をすべて優先する。
        self.pipeline.speak_sequence([("今の文です。", "transition_1"),
                                      ("続きです。", "transition_2")], speaker_id=3)
        task = self.queue("次の場面。" * 30)
        with patch("voicevox_client.requests.post", side_effect=lambda *a, **kw: audio_response()) as post:
            self.start(self.pipeline._generator_worker)
            self.assertTrue(task.done.wait(3))
            self.assertEqual(task.status, "ready")
            self.assertEqual(len(played), 2)
            self.assertEqual(post.call_count, 6)  # 現在文2回 + 次場面の先頭1回
            texts = [call.kwargs["params"]["text"] for call in post.call_args_list
                     if call.args[0].endswith("/audio_query")]
            self.assertEqual(texts[:2], ["今の文です。", "続きです。"])
            self.assertLessEqual(len(texts[2]), 80)
            self.assertTrue(texts[2].startswith("次の場面。"))

    def test_ready_prefetch_is_reused_without_http(self):
        task = self.queue()
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]) as post:
            self.pipeline._run_first_chunk_prefetch(task)
            wav = self.prepare()
            self.assertEqual(post.call_count, 2)
        self.assertEqual(wav.read_bytes(), b"RIFF-test-audio")
        self.assertEqual(next(row for row in self.rows() if row["stage"] == "voice_prefetch_use")["result"], "ready")
        self.assertFalse(list(self.cache.glob("voice-prefetch-*")))

    def test_transition_joins_running_synthesis_instead_of_duplicating(self):
        task = self.queue()
        entered, release, post = self.blocked_http()
        result, waiting = [], threading.Event()
        original_wait = task.done.wait
        def wait(timeout=None):
            waiting.set()
            return original_wait(timeout)
        with patch("voicevox_client.requests.post", side_effect=post) as request, patch.object(task.done, "wait", side_effect=wait):
            worker = self.start(lambda: self.pipeline._run_first_chunk_prefetch(task))
            self.assertTrue(entered.wait(3))
            self.pipeline.stop(preserve_prefetch=True)
            preparer = self.start(lambda: result.append(self.prepare()))
            self.assertTrue(waiting.wait(3))
            self.assertEqual(result, [])
            release.set()
            worker.join(3)
            preparer.join(3)
            self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].is_file())

    def test_normal_transition_preserves_unstarted_prefetch(self):
        task = self.queue()
        self.pipeline.stop(preserve_prefetch=True)
        self.assertIs(self.pipeline._generation_queue.get_nowait(), task)
        self.pipeline._generation_queue.task_done()
        self.assertFalse(task.done.is_set())
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]):
            self.pipeline._run_first_chunk_prefetch(task)
        self.assertEqual(task.status, "ready")
        self.assertEqual(self.pipeline._generation_queue.unfinished_tasks, 0)

    def test_stop_cancels_queued_job_without_http(self):
        task = self.queue()
        self.pipeline.stop()
        with patch("voicevox_client.requests.post") as post:
            self.pipeline._run_first_chunk_prefetch(task)
        post.assert_not_called()
        self.assertTrue(task.done.is_set())
        self.assertEqual(task.status, "cancelled")
        self.assertEqual(self.pipeline._generation_queue.unfinished_tasks, 0)

    def test_stop_and_cache_clear_do_not_publish_late_response(self):
        task = self.queue()
        entered, release, post = self.blocked_http()
        with patch("voicevox_client.requests.post", side_effect=post):
            worker = self.start(lambda: self.pipeline._run_first_chunk_prefetch(task))
            self.assertTrue(entered.wait(3))
            self.pipeline.stop()
            VoicevoxClient(cache_dir=self.cache).clear_all_cache()
            release.set()
            worker.join(3)
        self.assertEqual(task.status, "cancelled")
        self.assertFalse(list(self.cache.glob("*.wav")))
        self.assertFalse(list(self.cache.glob("voice-prefetch-*")))
        self.pipeline.on_error.assert_not_called()

    def test_prefetch_failure_is_silent_and_normal_preparation_retries(self):
        import requests
        task = self.queue()
        with patch("voicevox_client.requests.post", side_effect=requests.ConnectionError):
            self.pipeline._run_first_chunk_prefetch(task)
        self.assertEqual(task.status, "error")
        self.pipeline.on_error.assert_not_called()
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]) as post:
            self.assertTrue(self.prepare().is_file())
            self.assertEqual(post.call_count, 2)

    def test_changed_speaker_or_text_never_reuses_other_audio(self):
        for text, speaker in (("次の場面です。", 5), ("別の物語です。", 3)):
            with self.subTest(text=text, speaker=speaker):
                task = self.queue()
                with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]):
                    self.pipeline._run_first_chunk_prefetch(task)
                with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]) as post:
                    self.assertTrue(self.prepare(text, speaker).is_file())
                    self.assertEqual(post.call_count, 2)
                    self.assertEqual(post.call_args_list[0].kwargs["params"]["speaker"], speaker)
                VoicevoxClient(cache_dir=self.cache).clear_all_cache()

    def test_shutdown_discards_inflight_prefetch(self):
        task = self.queue()
        entered, release, post = self.blocked_http()
        with patch("voicevox_client.requests.post", side_effect=post):
            worker = self.start(lambda: self.pipeline._run_first_chunk_prefetch(task))
            self.assertTrue(entered.wait(3))
            self.pipeline.shutdown()
            release.set()
            worker.join(3)
        self.assertEqual(task.status, "cancelled")
        self.assertFalse(list(self.cache.glob("*.wav")))

    def test_stop_unblocks_transition_waiter_without_new_synthesis(self):
        task = self.queue()
        entered, release, post = self.blocked_http()
        waiting, results = threading.Event(), []
        original_wait = task.done.wait
        def wait(timeout=None):
            waiting.set()
            return original_wait(timeout)
        with patch("voicevox_client.requests.post", side_effect=post) as request, patch.object(task.done, "wait", side_effect=wait):
            worker = self.start(lambda: self.pipeline._run_first_chunk_prefetch(task))
            self.assertTrue(entered.wait(3))
            preparer = self.start(lambda: results.append(self.prepare()))
            self.assertTrue(waiting.wait(3))
            self.pipeline.stop()
            preparer.join(3)
            self.assertEqual(results, [None])
            release.set()
            worker.join(3)
            self.assertEqual(request.call_count, 2)
        self.assertFalse(list(self.cache.glob("*.wav")))

    def test_summary_tool_displays_prefetch_and_remaining_wait(self):
        import summarize_performance
        task = self.queue()
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), audio_response()]):
            self.pipeline._run_first_chunk_prefetch(task)
            self.prepare()
        output = summarize_performance.summarize(self.monitor.path)
        self.assertIn("次場面の先頭音声を事前準備: 準備完了", output)
        self.assertIn("事前準備の利用: 再利用", output)
        self.assertIn("残り待ち", output)


class PrefetchPresentationTests(unittest.TestCase):
    setUp = baseline.PresentationTests.setUp

    def scene(self):
        return Scene(2, "次章", "続きです", "進む", "待つ", "a", "結末", "終わり")

    def prepare_result(self):
        self.app._prepare_narrative(display_text="正解です", voice_parts=[("正解です", "transition")],
                                    next_voice_scene=self.scene())

    def finish_preparing(self):
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.prepare_result()
        self.callbacks.pop()()

    def test_prefetch_starts_only_after_current_voice_was_queued(self):
        self.finish_preparing()
        calls = self.app.voice_pipeline.method_calls
        names = [call[0] for call in calls]
        self.assertLess(names.index("speak_sequence"), names.index("prefetch_first_chunk"))
        expected = self.app._scene_voice_parts(self.scene())
        self.assertEqual(self.app.voice_pipeline.prefetch_first_chunk.call_args.args[0], expected)
        self.assertEqual(expected, [("次章。続きです。選択肢a、進む。選択肢b、待つ。", "scene_2")])

    def test_voice_off_and_disabled_setting_never_prefetch(self):
        import main
        self.prepare_result()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        with patch.dict(main.SETTINGS["voicevox"], prefetch_next_scene_first_chunk=False):
            self.finish_preparing()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()

    def test_stop_before_preparation_finishes_does_not_restart_voice_or_prefetch(self):
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.prepare_result()
        self.app.stop_voice()
        self.callbacks.pop()()
        self.app._start_typing.assert_called_once()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()

    def test_stale_presentation_never_schedules_prefetch(self):
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.prepare_result()
        self.app.presentation_id += 1
        self.callbacks.pop()()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()

    def test_correct_result_passes_next_scene_but_does_not_display_it(self):
        scene = self.scene()
        self.app._reset_choice_buttons = Mock()
        self.app._prepare_narrative = Mock()
        self.app._show_scene = Mock()
        self.app._play_sound_effect_then = Mock(side_effect=lambda path, action, **kw: action())
        self.app._handle_result(dict(status="next_scene", result_text="正解結果", scene=scene))
        self.assertIs(self.app._prepare_narrative.call_args.kwargs["next_voice_scene"], scene)
        self.app._show_scene.assert_not_called()

    def test_scene_preparation_preserves_prefetch_and_uses_matching_text(self):
        scene = self.scene()
        self.app.retry_button = Mock()
        self.app._reset_choice_buttons = Mock()
        self.app._prepare_narrative = Mock()
        self.app._show_scene(scene)
        options = self.app._prepare_narrative.call_args.kwargs
        self.assertTrue(options["preserve_voice_prefetch"])
        self.assertEqual(options["voice_parts"], self.app._scene_voice_parts(scene))
