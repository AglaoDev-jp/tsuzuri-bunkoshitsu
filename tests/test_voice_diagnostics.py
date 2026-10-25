"""固定文の同条件比較、失敗時の継続、GUIを止めない計測を確認する。"""
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
import wave
from unittest.mock import Mock, patch

import test_measurement as baseline
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from performance_monitor import APP_VERSION, PerformanceMonitor
from voice_diagnostics import PROBE_TEXT, engine_information, format_report, run_diagnostic
from voicevox_client import VoicePipeline, VoicevoxClient, VoicevoxError


def pcm_response(seconds=2):
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * (24000 * seconds))
    result = baseline.response({})
    result._content = data.getvalue()
    return result


def metadata_get(url, **kwargs):
    if url.endswith("/version"):
        return baseline.response("test-engine")
    if url.endswith("/supported_devices"):
        return baseline.response({"cpu": True, "cuda": True, "dml": False})
    return baseline.response(False)


class VoiceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.monitor = PerformanceMonitor(self.root / "logs", enabled=True)
        self.trace = self.monitor.start("voice_diagnostic")

    def run_probe(self, **kwargs):
        return run_diagnostic(base_url="http://voice.test", speaker_id=7,
                              performance=self.monitor, trace=self.trace, **kwargs)

    def rows(self):
        return [json.loads(line) for line in self.monitor.path.read_text(encoding="utf-8").splitlines()]

    def test_same_text_and_speaker_in_game_and_standalone_with_no_wav_cache_hits(self):
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get) as get, patch(
            "voicevox_client.requests.post", side_effect=lambda url, **kw: (
                baseline.response({"speedScale": 1.0}) if url.endswith("/audio_query") else pcm_response()
            )
        ) as post:
            game = self.run_probe(source="game_idle")
            standalone = self.run_probe(source="standalone")
        self.assertEqual(post.call_count, 12)  # 3試行×2API×2条件
        queries = [c for c in post.call_args_list if c.args[0].endswith("/audio_query")]
        self.assertTrue(all(c.kwargs["params"] == {"text": PROBE_TEXT, "speaker": 7} for c in queries))
        self.assertEqual(len({r["text_sha256"] for r in game["trials"] + standalone["trials"]}), 1)
        self.assertTrue(all(not r["cache_hit"] for r in game["trials"] + standalone["trials"]))
        self.assertEqual([r["trial_kind"] for r in game["trials"]], ["first_measured", "repeat", "repeat"])
        self.assertEqual(get.call_count, 6)
        self.assertTrue(all(c.kwargs["timeout"] == 2 for c in get.call_args_list))
        self.assertEqual(game["active_device"], None)  # CUDA対応でもGPU稼働中とは判定しない
        self.assertEqual(game["app_version"], APP_VERSION)
        self.assertNotIn(PROBE_TEXT, self.monitor.path.read_text(encoding="utf-8"))

    def test_wav_metrics_and_rtf_preserve_original_api_payload_and_bytes(self):
        voice = VoicevoxClient(cache_dir=self.root / "cache", performance=self.monitor,
                               performance_trace=self.trace)
        query = baseline.response({"speedScale": 1.25, "outputSamplingRate": 24000})
        audio = pcm_response()
        with patch("voicevox_client.requests.post", side_effect=[query, audio]) as post:
            path = voice.create_or_get_audio("テスト。", cache_key="test")
        row = self.rows()[-1]
        self.assertEqual(row["audio_seconds"], 2)
        self.assertEqual(row["sample_rate"], 24000)
        self.assertEqual(row["channels"], 1)
        self.assertAlmostEqual(row["synthesis_rtf"], row["synthesis_ms"] / 2000)
        self.assertEqual(path.read_bytes(), audio.content)
        self.assertEqual(post.call_args_list[1].kwargs, {
            "params": {"speaker": 3}, "data": query.text, "timeout": 60,
        })
        with patch("voicevox_client.requests.post") as post:
            self.assertEqual(voice.create_or_get_audio("テスト。", cache_key="test"), path)
        post.assert_not_called()
        self.assertTrue(self.rows()[-1]["cache_hit"])
        self.assertNotIn("synthesis_rtf", self.rows()[-1])

    def test_unreadable_wav_metadata_does_not_reject_previously_accepted_audio(self):
        voice = VoicevoxClient(cache_dir=self.root / "cache", performance=self.monitor, performance_trace=self.trace)
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), baseline.response({})]):
            self.assertTrue(voice.create_or_get_audio("文章", cache_key="legacy").is_file())
        self.assertTrue(self.rows()[-1]["wav_metadata_unavailable"])
        self.assertEqual(self.rows()[-1]["status"], "ok")

    def test_zero_audio_length_has_no_division_error_or_fabricated_rtf(self):
        details = {"synthesis_ms": 10}
        VoicevoxClient._record_wav_metrics(pcm_response(0).content, details)
        self.assertEqual(details["audio_seconds"], 0)
        self.assertNotIn("synthesis_rtf", details)

    def test_metadata_failure_does_not_block_synthesis(self):
        import requests
        with patch("voice_diagnostics.requests.get", side_effect=requests.Timeout), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()]
        ):
            report = self.run_probe(samples=1)
        self.assertIsNone(report["engine_version"])
        self.assertIsNone(report["speaker_initialized_before"])
        self.assertEqual(len(report["metadata_errors"]), 3)
        self.assertEqual(report["trials"][0]["status"], "ok")

    def test_failure_is_logged_with_phase_and_stops_remaining_trials(self):
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), baseline.response({}, status=500)]
        ) as post:
            report = self.run_probe()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(report["trials"]), 1)
        row = report["trials"][0]
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["phase"], "synthesis")
        self.assertEqual(row["synthesis_http_status"], 500)
        self.assertEqual(row["error_type"], "VoicevoxError")
        self.assertIn("失敗工程: synthesis", format_report(report))

    def test_cancellation_between_trials_cleans_temporary_audio(self):
        event = threading.Event()
        paths = []
        original = VoicevoxClient.create_or_get_audio
        def create(client, *args, **kwargs):
            paths.append(client.cache_dir)
            value = original(client, *args, **kwargs)
            event.set()
            return value
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()]
        ), patch.object(VoicevoxClient, "create_or_get_audio", create):
            report = self.run_probe(cancel_event=event)
        self.assertTrue(report["cancelled"])
        self.assertEqual(len(report["trials"]), 1)
        self.assertFalse(paths[0].exists())
        self.assertNotEqual(paths[0], self.root / "cache")

    def test_cancelled_before_start_performs_no_http(self):
        event = threading.Event()
        event.set()
        with patch("voice_diagnostics.requests.get") as get, patch("voicevox_client.requests.post") as post:
            self.assertTrue(self.run_probe(cancel_event=event)["cancelled"])
        get.assert_not_called()
        post.assert_not_called()

    def test_invalid_limits_do_not_start_http(self):
        with patch("voice_diagnostics.requests.get") as get:
            for n in (0, 6):
                with self.assertRaises(ValueError):
                    self.run_probe(samples=n)
        get.assert_not_called()

    def test_disabled_or_failed_log_does_not_change_diagnostic_result(self):
        disabled = PerformanceMonitor()
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()]
        ):
            report = run_diagnostic(base_url="http://voice.test", speaker_id=7, samples=1, performance=disabled)
        self.assertEqual(report["trials"][0]["status"], "ok")
        self.assertIsNone(disabled.path)

    def test_cli_uses_config_and_requested_speaker_without_game_initialization(self):
        import diagnose_voicevox
        report = {"source": "standalone", "speaker_id": 8, "probe_id": "test", "cancelled": False,
                  "trials": [{"status": "ok", "sample": 1}]}
        with patch("diagnose_voicevox.run_diagnostic", return_value=report) as run, patch("builtins.print"):
            self.assertEqual(diagnose_voicevox.main(["--speaker", "8", "--samples", "1"]), 0)
        self.assertEqual(run.call_args.kwargs["speaker_id"], 8)
        self.assertEqual(run.call_args.kwargs["samples"], 1)
        self.assertEqual(run.call_args.kwargs["source"], "standalone")

    def test_log_write_failure_does_not_abort_synthesis(self):
        self.monitor.write_failed = True
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()]
        ):
            report = self.run_probe(samples=1)
        self.assertEqual(report["trials"][0]["status"], "ok")
        self.assertTrue(self.monitor.write_failed)

    def test_summary_tool_handles_diagnostic_and_old_logs(self):
        from summarize_performance import summarize
        with patch("voice_diagnostics.requests.get", side_effect=metadata_get), patch(
            "voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()]
        ):
            self.run_probe(samples=1)
        output = summarize(self.monitor.path)
        for text in ("固定文計測", "合成HTTP", "実時間比", "CPU/GPU稼働モード: 未確認"):
            self.assertIn(text, output)

    def test_queue_measurement_stays_with_its_original_trace(self):
        with patch("voicevox_client.threading.Thread.start"):
            pipeline = VoicePipeline(base_url="http://voice.test", cache_dir=self.root / "cache")
        self.addCleanup(pipeline.shutdown)
        pipeline._put_playback_job = Mock()
        pipeline.speak_sequence([("最初の文。", "first"), ("次の文。", "second")], speaker_id=7,
                                performance=self.monitor, performance_trace=self.trace)
        other = self.monitor.start("unrelated")
        pipeline._generation_queue.put(None)
        with patch("voicevox_client.requests.post", side_effect=[baseline.response({}), pcm_response()] * 2):
            pipeline._generator_worker()
        self.assertEqual(pipeline._put_playback_job.call_count, 2)
        rows = self.rows()
        generated = [r for r in rows if r["stage"] == "voice_generation_started"]
        self.assertEqual(len(generated), 2)
        self.assertTrue(all(r["trace_id"] == self.trace.trace_id and r["queue_wait_ms"] >= 0 for r in generated))
        self.assertNotEqual(other.trace_id, self.trace.trace_id)
        audio = [r for r in rows if r["stage"] == "voice_audio"]
        self.assertEqual(len(audio), 2)
        self.assertTrue(all(r["voice_role"] == "playback_generation" for r in audio))
        self.assertEqual(pipeline._generation_queue.unfinished_tasks, 0)


class DiagnosticPresentationTests(unittest.TestCase):
    def setUp(self):
        import main
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = main.AdventureApp.__new__(main.AdventureApp)
        app = self.app
        app.voice_diagnostic_active = False
        app._voice_diagnostic_cancel = threading.Event()
        app._voice_diagnostic_poll_id = None
        app._closing = False
        app.busy, app.typing_active, app.narrative_voice_done = False, False, True
        app.engine = None
        app.speaker_var = Mock(get=Mock(return_value="7"))
        app.voice_diagnostic_button = Mock()
        app.root = Mock()
        app._set_busy = Mock()
        app.performance_trace = object()
        app.voice_pipeline = Mock()
        self.log_dir = patch("main.LOG_DIR", Path(self.directory.name))
        self.log_dir.start()
        self.addCleanup(self.log_dir.stop)

    def test_gui_uses_captured_speaker_and_restores_controls_without_changing_trace(self):
        report = {"source": "game_idle", "speaker_id": 7, "probe_id": "test", "trials": [], "cancelled": False}
        before = self.app.performance_trace
        with patch("main.threading.Thread", side_effect=lambda target, **kw: Mock(start=target)), patch(
            "main.run_diagnostic", return_value=report
        ) as run, patch("main.messagebox.showinfo") as info:
            self.app.start_voice_diagnostic()
        self.assertEqual(run.call_args.kwargs["speaker_id"], 7)
        self.assertEqual(run.call_args.kwargs["source"], "game_idle")
        self.assertEqual([c.args for c in self.app._set_busy.call_args_list], [(True,), (False,)])
        self.assertIs(self.app.performance_trace, before)
        self.assertFalse(self.app.voice_diagnostic_active)
        self.assertEqual(self.app.voice_pipeline.method_calls, [])
        info.assert_called_once()

    def test_generation_or_playback_in_progress_prevents_diagnostic(self):
        for field, value in (("busy", True), ("typing_active", True), ("narrative_voice_done", False),
                             ("engine", Mock(finished=False))):
            with self.subTest(field=field), patch("main.threading.Thread") as thread, patch("main.messagebox.showinfo"):
                original = getattr(self.app, field)
                setattr(self.app, field, value)
                self.app.start_voice_diagnostic()
                setattr(self.app, field, original)
                thread.assert_not_called()

    def test_cancel_button_sets_event_and_prevents_duplicate_worker(self):
        self.app.voice_diagnostic_active = True
        with patch("main.threading.Thread") as thread:
            self.app.start_voice_diagnostic()
        self.assertTrue(self.app._voice_diagnostic_cancel.is_set())
        thread.assert_not_called()

    def test_closed_gui_ignores_late_results(self):
        self.app._closing = True
        results = queue.Queue()
        results.put((None, "test error"))
        with patch("main.messagebox.showerror") as error:
            self.app._poll_voice_diagnostic(results, PerformanceMonitor())
        self.app._set_busy.assert_not_called()
        self.app.voice_diagnostic_button.config.assert_not_called()
        error.assert_not_called()

    def test_unexpected_worker_failure_restores_controls(self):
        with patch("main.threading.Thread", side_effect=lambda target, **kw: Mock(start=target)), patch(
            "main.run_diagnostic", side_effect=RuntimeError("test")
        ), patch("main.messagebox.showerror") as error:
            self.app.start_voice_diagnostic()
        self.assertFalse(self.app.voice_diagnostic_active)
        self.app._set_busy.assert_called_with(False)
        error.assert_called_once()

    def test_waiting_polls_on_gui_thread_without_blocking(self):
        self.app._poll_voice_diagnostic(queue.Queue(), PerformanceMonitor())
        self.assertEqual(self.app.root.after.call_args.args[0], 100)
        self.app._set_busy.assert_not_called()
