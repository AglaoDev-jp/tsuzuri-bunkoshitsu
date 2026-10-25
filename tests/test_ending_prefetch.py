"""エンディングの表示順・手動続行・無音区間・先読みの取消を確認する。"""
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch
import unittest

import test_measurement as baseline
import test_voice_prefetch as existing_prefetch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from game_engine import Scene
from voicevox_client import VoicevoxClient


class EndingPresentationTests(unittest.TestCase):
    setUp = baseline.PresentationTests.setUp

    def stages(self):
        """実際のGOOD ENDハンドラーが組み立てる文章・キーをそのまま使う。"""
        scene = Scene(5, "帰還", "旅を終える", "帰る", "待つ", "a", "別れ", "終わり",
                      background_tag="room", bgm_tag="calm")
        self.app.engine = Mock(current_scene=scene)
        self.app._reset_choice_buttons = Mock()
        self.app.retry_button = Mock()
        self.app._play_sound_effect_then = Mock(side_effect=lambda path, action, **kw: action())
        with patch.object(self.app, "_play_ending_sequence") as play:
            self.app._handle_result(dict(status="good_end", title="帰還", text="町へ戻った。",
                                         epilogue="いつもの日常。", clear_message="無事にクリア。",
                                         ai_comment="立派な冒険でした。", play_judgement="慎重な旅人",
                                         bad_end_count=1, retry_count=1, choice_count=6))
        return play.call_args.args[0]

    def start_stage(self, stages, index=0):
        # HTTPワーカーの戻りとTkのコールバックを、テストから個別に進める。
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.app._play_ending_sequence(stages, index)
        if self.callbacks:
            self.callbacks.pop(0)()

    def test_target_keys_skip_silent_record_but_preserve_display_and_audio(self):
        stages = self.stages()
        expected = ["good_ending_epilogue", "good_ending_clear", "good_ending_comment",
                    "good_ending_thanks", "good_ending_thanks", None]
        with patch.object(self.app, "_prepare_narrative") as prepare:
            for index, target in enumerate(expected):
                self.app._play_ending_sequence(stages, index)
                opts = prepare.call_args.kwargs
                self.assertEqual(opts["display_text"], stages[index][0])
                self.assertEqual(opts["voice_parts"], stages[index][1])
                self.assertEqual(opts["background_tag"], stages[index][2])
                self.assertEqual(opts["result_image_key"], stages[index][3])
                self.assertEqual(opts["bgm_tag"], stages[index][4])
                self.assertEqual(opts["next_voice_parts"][0][1] if target else None, target)
                self.assertEqual(opts["preserve_voice_prefetch"], index > 0)
                self.assertEqual(opts["voice_prefetch_kind"], "ending")

    def test_all_six_stages_wait_for_manual_continue_and_both_completions(self):
        import main
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        self.app._show_continue_button = Mock()
        self.app._finish_game_clear_sequence = Mock()
        scheduled = []
        self.app._schedule_presentation_action = Mock(side_effect=lambda delay, action: scheduled.append((delay, action)))
        self.start_stage(stages)
        for index, stage in enumerate(stages):
            self.assertEqual(self.app._start_typing.call_args.args[0], stage[0])
            self.assertEqual(self.app._show_continue_button.call_count, index)
            # 文字完了だけでは、読み上げ中の区間から次へ進めない。
            self.app._start_typing.call_args.kwargs["on_complete"]()
            if stage[1]:
                self.assertEqual(self.app._show_continue_button.call_count, index)
                self.app.voice_pipeline.speak_sequence.call_args.kwargs["on_complete"]()
                self.callbacks.pop(0)()
            if index == 5:
                self.app._finish_game_clear_sequence.assert_called_once()
                break
            self.app._finish_game_clear_sequence.assert_not_called()
            self.assertEqual(self.app._show_continue_button.call_count, index + 1)
            self.assertEqual(len(scheduled), 0)  # ボタンを押すまでは予約もしない。
            action = self.app._show_continue_button.call_args.kwargs["action"]
            action()
            delay, proceed = scheduled.pop()
            self.assertEqual(delay, main.ENDING_SECTION_PAUSE_MS)
            self.assertEqual(delay, 500)
            with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
                proceed()
            if self.callbacks:
                self.callbacks.pop(0)()
        self.assertEqual(self.app._start_typing.call_count, 6)
        self.assertEqual(self.app.voice_pipeline.speak_sequence.call_count, 5)
        queued = self.app.voice_pipeline.prefetch_first_chunk.call_args_list
        self.assertEqual([c.args[0][0][1] for c in queued], ["good_ending_epilogue", "good_ending_clear",
                                                          "good_ending_comment", "good_ending_thanks"])
        self.assertTrue(all(c.kwargs["prefetch_kind"] == "ending" for c in queued))

    def test_current_voice_is_queued_before_prefetch_and_future_text_stays_hidden(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        self.start_stage(stages)
        calls = [c[0] for c in self.app.voice_pipeline.method_calls]
        self.assertLess(calls.index("speak_sequence"), calls.index("prefetch_first_chunk"))
        self.assertEqual(self.app._start_typing.call_args.args[0], stages[0][0])
        self.app._append_backlog.assert_not_called()
        self.assertNotIn("いつもの日常", self.app._start_typing.call_args.args[0])

    def test_silent_record_preserves_prefetch_without_synthesis_or_replay(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        self.app.voice_pipeline.reset_mock()
        self.start_stage(stages, 4)
        self.app.voice_pipeline.stop.assert_called_once_with(preserve_prefetch=True)
        self.app.voice_pipeline.prepare_first_chunk.assert_not_called()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.assertIsNone(self.app.pending_voice_prefetch)
        self.assertEqual(self.app._start_typing.call_args.args[0], stages[4][0])

    def test_voice_off_displays_all_stages_without_voice_preparation(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = False
        for index in range(6):
            self.start_stage(stages, index)
        self.assertEqual(self.app._start_typing.call_count, 6)
        self.app.voice_pipeline.prepare_first_chunk.assert_not_called()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.assertTrue(all(c.kwargs == {"preserve_prefetch": False}
                            for c in self.app.voice_pipeline.stop.call_args_list if c.kwargs))

    def test_ending_switch_does_not_depend_on_next_scene_switch(self):
        import main
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        with patch.dict(main.SETTINGS["voicevox"], prefetch_next_scene_first_chunk=False, prefetch_ending_first_chunk=True):
            self.start_stage(stages)
        self.app.voice_pipeline.prefetch_first_chunk.assert_called_once()

    def test_ending_switch_off_uses_existing_display_time_preparation(self):
        import main
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        with patch.dict(main.SETTINGS["voicevox"], prefetch_ending_first_chunk=False):
            self.start_stage(stages, 1)
        self.app.voice_pipeline.prepare_first_chunk.assert_called_once()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app.voice_pipeline.stop.assert_called_with(preserve_prefetch=False)

    def test_stop_before_preparation_finishes_does_not_start_ending_prefetch(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.app._play_ending_sequence(stages)
        self.app.stop_voice()
        self.callbacks.pop(0)()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app.voice_pipeline.speak_sequence.assert_not_called()
        self.app._start_typing.assert_called_once()

    def test_stale_presentation_does_not_start_ending_prefetch(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        with patch("main.threading.Thread", side_effect=lambda target, args, **kw: Mock(start=lambda: target(*args))):
            self.app._play_ending_sequence(stages)
        self.app.presentation_id += 1
        self.callbacks.pop(0)()
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app._start_typing.assert_not_called()

    def test_last_thanks_does_not_schedule_another_prefetch(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        self.start_stage(stages, 5)
        self.app.voice_pipeline.prefetch_first_chunk.assert_not_called()
        self.app.voice_pipeline.prepare_first_chunk.assert_called_once_with(
            stages[5][1], speaker_id=3, performance=self.app.performance,
            performance_trace=self.app.performance_trace,
        )

    def test_first_good_end_still_uses_normal_first_chunk_preparation(self):
        stages = self.stages()
        self.app.voice_enabled_var.get.return_value = True
        self.app.voice_pipeline.reset_mock()
        self.start_stage(stages)
        self.app.voice_pipeline.stop.assert_called_once_with(preserve_prefetch=False)
        self.app.voice_pipeline.prepare_first_chunk.assert_called_once_with(
            stages[0][1], speaker_id=3, performance=self.app.performance,
            performance_trace=self.app.performance_trace,
        )
        self.assertEqual(self.app.voice_pipeline.prefetch_first_chunk.call_args.args[0], stages[1][1])


class EndingPipelineTests(unittest.TestCase):
    # 実際の生成キュー・キャッシュを使う。常駐スレッドの再生だけを代替する。
    setUp = existing_prefetch.PrefetchTests.setUp
    tearDown = existing_prefetch.PrefetchTests.tearDown
    start = existing_prefetch.PrefetchTests.start
    blocked_http = existing_prefetch.PrefetchTests.blocked_http
    rows = existing_prefetch.PrefetchTests.rows

    def queue(self, text="エピローグ。次の物語です。", speaker=3):
        self.parts = [(text, "good_ending_epilogue")]
        self.pipeline.prefetch_first_chunk(self.parts, speaker_id=speaker, prefetch_kind="ending",
                                           performance=self.monitor, performance_trace=self.trace)
        return self.pipeline._first_chunk_prefetch

    def prepare(self, text=None, speaker=3):
        parts = [(text, "good_ending_epilogue")] if text else self.parts
        return self.pipeline.prepare_first_chunk(parts, speaker_id=speaker,
                                                performance=self.monitor, performance_trace=self.trace)

    # 待機の共有・中止・再プレイ時の保護を、ending種別でも実スレッドで検証する。
    test_ending_transition_joins_inflight_synthesis = existing_prefetch.PrefetchTests.test_transition_joins_running_synthesis_instead_of_duplicating
    test_ending_stop_and_replay_discard_late_audio = existing_prefetch.PrefetchTests.test_stop_and_cache_clear_do_not_publish_late_response
    test_ending_failure_falls_back_to_normal_preparation = existing_prefetch.PrefetchTests.test_prefetch_failure_is_silent_and_normal_preparation_retries
    test_ending_shutdown_discards_inflight_audio = existing_prefetch.PrefetchTests.test_shutdown_discards_inflight_prefetch

    def test_only_first_chunk_is_generated_and_reused_across_silent_stage(self):
        task = self.queue("エピローグ。" * 40)
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), existing_prefetch.audio_response()]) as post:
            self.pipeline._run_first_chunk_prefetch(task)
            self.pipeline.stop(preserve_prefetch=True)  # 無音のプレイ記録へ移る
            self.assertIs(self.pipeline._first_chunk_prefetch, task)
            result = self.prepare()
            self.assertEqual(post.call_count, 2)
        self.assertTrue(result.is_file())
        events = self.rows()
        tagged = [r for r in events if r["stage"].startswith("voice_prefetch_")]
        self.assertTrue(all(r["prefetch_kind"] == "ending" for r in tagged))
        self.assertEqual(next(r for r in events if r["stage"] == "voice_audio")["voice_role"], "ending_prefetch")
        self.assertLessEqual(next(r for r in tagged if r["stage"] == "voice_prefetch_queued")["characters"], 80)
        self.assertTrue(self.pipeline._playback_queue.empty())

    def test_changed_speaker_does_not_reuse_prefetched_ending(self):
        task = self.queue()
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), existing_prefetch.audio_response()]):
            self.pipeline._run_first_chunk_prefetch(task)
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), existing_prefetch.audio_response()]) as post:
            result = self.prepare(speaker=7)
        self.assertTrue(result.is_file())
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["params"]["speaker"], 7)

    def test_ending_events_are_distinguished_in_summary(self):
        from summarize_performance import summarize
        task = self.queue()
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), existing_prefetch.audio_response()]):
            self.pipeline._run_first_chunk_prefetch(task)
            self.prepare()
        result = summarize(self.monitor.path)
        self.assertIn("エンディングの先頭音声を事前準備: 準備完了", result)
        self.assertIn("事前準備の利用: 再利用", result)
        self.assertIn("エンディングの先読み", result)


class DiagnosticGuardTests(unittest.TestCase):
    def test_diagnostic_does_not_compete_with_ending_prefetch_between_stages(self):
        from test_voice_diagnostics import DiagnosticPresentationTests
        DiagnosticPresentationTests.setUp(self)
        self.app.engine = Mock(finished=True)
        self.app.game_clear_complete = False
        with patch("main.threading.Thread") as thread, patch("main.messagebox.showinfo"):
            self.app.start_voice_diagnostic()
        thread.assert_not_called()
