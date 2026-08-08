"""
VOICEVOXによる音声生成、WAVキャッシュ、連続再生を行うモジュール。

音声をできるだけスムーズに再生できるよう、
処理は次の流れで進めています。

``文章を短く分割
→ 生成キュー
→ VOICEVOXでWAV生成
→ 再生キュー
→ pygameで順番に再生``

音声の生成と再生を別スレッドで動かすことで、
先頭の音声を再生している間に、次の音声を裏側で準備できます。
そのため、待ち時間が短く感じられ、より自然な再生になります。

また、各リクエストには ``request_id`` を付けています。
これにより、場面が切り替わったあとに、
前のシーンの音声が流れてしまうことを防いでいます。

役割は次のように分けています。

- ``VoicevoxClient``
    VOICEVOXとの通信、WAVファイルの生成、キャッシュ管理を担当します。
- ``VoicePipeline``
    複数の音声を順番に管理し、生成・再生の流れを制御します。

このように役割を分けておくことで、
それぞれのクラスが担当する処理をシンプルに保ち、
あとから機能を追加したり修正したりしやすくしています。
"""

from __future__ import annotations

import hashlib
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame
import requests

from audio_mixer import (
    MIXER_LOCK,
    RESERVED_CHANNEL_COUNT,
    SFX_CHANNEL_INDEX,
    ensure_mixer_initialized_locked,
)


class VoicevoxError(RuntimeError):
    """VOICEVOX通信、音声保存、または再生に関するアプリ用例外。"""


@dataclass(frozen=True)
class VoiceJob:
    """生成キューへ渡す、1音声チャンク分の変更不可データ。"""

    # request_idは、このジョブが現在の読み上げ要求に属するかの判定に使う。
    request_id: int
    cache_key: str
    text: str
    speaker_id: int
    index: int
    # 最後のチャンクだけが完了通知を持つ。途中のチャンクでは呼び出さない。
    on_complete: Callable[[], None] | None = None


@dataclass(frozen=True)
class AudioJob:
    """再生キューへ渡す、生成済みWAVの情報。"""

    request_id: int
    wav_path: Path
    # 対応する読み上げ要求が最後まで再生されたことを上位へ知らせる。
    on_complete: Callable[[], None] | None = None


class VoicevoxClient:
    """
    VOICEVOXのHTTP APIとWAVキャッシュを扱う同期クライアント。

    このクラス自身はスレッドを作らない。GUIを止めないための並行処理は、
    呼び出し側の ``VoicePipeline`` または ``main.py`` が担当する。
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:50021",
        speaker_id: int = 3,
        cache_dir: Path | None = None,
    ) -> None:
        """接続先、話者ID、キャッシュ保存先を初期化する。"""
        # APIパス連結時の二重スラッシュを防ぐ。
        self.base_url = base_url.rstrip("/")
        self.speaker_id = speaker_id
        self.cache_dir = cache_dir

        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        """短いタイムアウトでVOICEVOXの起動状態を確認する。"""
        try:
            response = requests.get(f"{self.base_url}/version", timeout=2)
            response.raise_for_status()
            return True
        except requests.RequestException:
            # 起動確認用途なので詳細例外は外へ出さず、真偽値だけを返す。
            return False

    def create_or_get_audio(
        self,
        text: str,
        *,
        cache_key: str,
    ) -> Path:
        """
        文章のWAVを取得し、同じ条件のキャッシュがあれば再利用する。

        VOICEVOXの音声生成は2段階APIである。最初に ``audio_query`` で
        発音・アクセント等の設計データを作り、それを ``synthesis`` へ渡して
        WAVバイナリを得る。
        """

        # 画面用の装飾を除いてから、読み上げ可否とキャッシュ同一性を判断する。
        cleaned = clean_text_for_voice(text)
        if not cleaned:
            raise VoicevoxError("読み上げる文章がありません。")

        wav_path = self._make_cache_path(
            cleaned_text=cleaned,
            cache_key=cache_key,
        )
        # ファイルが存在しても0バイトなら壊れたキャッシュなので再生成する。
        if wav_path.exists() and wav_path.stat().st_size > 0:
            return wav_path

        try:
            # 第1段階: 読み上げ文章と話者から、音声合成用クエリを作る。
            query = requests.post(
                f"{self.base_url}/audio_query",
                params={"text": cleaned, "speaker": self.speaker_id},
                timeout=30,
            )
            query.raise_for_status()

            # 第2段階: 作成済みクエリを本文として送り、WAVを合成する。
            synthesis = requests.post(
                f"{self.base_url}/synthesis",
                params={"speaker": self.speaker_id},
                data=query.text,
                timeout=60,
            )
            synthesis.raise_for_status()

            # 通信成功後にバイナリを保存し、0バイトでないことまで確認する。
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(synthesis.content)
            if wav_path.stat().st_size == 0:
                wav_path.unlink(missing_ok=True)
                raise VoicevoxError("生成された音声ファイルが空でした。")
            return wav_path

        except requests.exceptions.ConnectionError as exc:
            # 途中まで作られた不完全ファイルを残さない。
            wav_path.unlink(missing_ok=True)
            raise VoicevoxError(
                "VOICEVOXに接続できません。VOICEVOXを起動してください。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            wav_path.unlink(missing_ok=True)
            raise VoicevoxError("VOICEVOXの音声生成がタイムアウトしました。") from exc
        except requests.RequestException as exc:
            wav_path.unlink(missing_ok=True)
            raise VoicevoxError(f"VOICEVOX通信エラー: {exc}") from exc
        except OSError as exc:
            wav_path.unlink(missing_ok=True)
            raise VoicevoxError(f"音声キャッシュ保存エラー: {exc}") from exc

    def delete_cache_group(self, cache_key: str) -> None:
        """
        指定キーを接頭辞に持つ音声キャッシュをまとめて削除する。

        1場面が複数チャンクへ分かれても共通接頭辞を持つため、場面単位で
        一括削除できる。
        """
        if self.cache_dir is None:
            return

        safe_key = self._safe_cache_key(cache_key)
        for path in self.cache_dir.glob(f"{safe_key}_*.wav"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # キャッシュ削除失敗はゲーム進行を止める重大エラーではない。
                pass

    def clear_all_cache(self) -> None:
        """キャッシュフォルダ直下のWAVをすべて削除する。"""
        if self.cache_dir is None:
            return

        for path in self.cache_dir.glob("*.wav"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _make_cache_path(self, *, cleaned_text: str, cache_key: str) -> Path:
        """
        人が判別できる接頭辞と内容ハッシュから、再利用可能なWAVパスを作る。

        ハッシュには接続先・話者・整形済み文章を含める。同じ文章でも話者が
        違えば別ファイルになり、誤った声のキャッシュを使わずに済む。
        """
        if self.cache_dir is None:
            raise VoicevoxError("音声キャッシュ保存先が設定されていません。")

        safe_key = self._safe_cache_key(cache_key)
        source = f"{self.base_url}|{self.speaker_id}|{cleaned_text}".encode("utf-8")
        # SHA-256の先頭16桁で、ファイル名を短くしつつ実用上十分に衝突を避ける。
        digest = hashlib.sha256(source).hexdigest()[:16]
        return self.cache_dir / f"{safe_key}_{digest}.wav"

    @staticmethod
    def _safe_cache_key(cache_key: str) -> str:
        """キャッシュキーを、Windows等でも扱いやすいファイル名へ正規化する。"""
        safe = re.sub(r"[^0-9A-Za-z_-]+", "_", cache_key)
        return safe.strip("_") or "voice"


class VoicePipeline:
    """
    常駐する音声生成・再生パイプライン。

    - 文章を短いチャンクへ分割する
    - 生成できたチャンクから即座に再生する
    - 後続チャンクは再生中に先行生成する
    - 同じ場面を再度読む場合はWAVキャッシュを再利用する
    - pygame.mixerはアプリ終了まで維持する

    生成キューは無制限、再生キューは最大3件。
    再生待ちが増えると、生成側は空きができるまで少し待機。

    こうすることで、再生しきれない大量のWAVデータが
    メモリ上にたまり続けるのを防げます。
    このように、後ろの処理速度に合わせて前の処理もペースを調整する仕組みを
    「バックプレッシャー（Back Pressure）」と呼びます。
    ストリーミング処理やメッセージキューなどでもよく使われる考え方です。
    """

    def __init__(
        self,
        *,
        base_url: str,
        cache_dir: Path,
        voice_volume: float = 1.0,
        sfx_volume: float = 1.0,
        on_error: Callable[[str], None] | None = None,
        on_sfx_warning: Callable[[str], None] | None = None,
    ) -> None:
        """キュー、排他制御、停止通知、2本の常駐スレッドを初期化する。"""
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.on_error = on_error
        self.on_sfx_warning = on_sfx_warning
        # VOICEVOXと効果音は別の再生先を使うため、音量も独立して保持する。
        # 0.0～1.0へ収めておけば、設定ファイルと画面スライダーのどちらから
        # 値を受け取ってもpygameへ安全に渡せる。
        self._voice_volume = self._normalize_volume(voice_volume)
        self._sfx_volume = self._normalize_volume(sfx_volume)

        # Noneはスレッドを終了させる番兵（sentinel）として使う。
        self._generation_queue: queue.Queue[VoiceJob | None] = queue.Queue()
        self._playback_queue: queue.Queue[AudioJob | None] = queue.Queue(maxsize=3)

        # request_lockは要求世代ID、mixer_lockはpygameの同時操作を保護する。
        self._request_lock = threading.Lock()
        # BGM管理側と同じロックを共有し、pygame.mixerの短い操作同士が
        # 別スレッドから同時実行されないようにする。
        self._mixer_lock = MIXER_LOCK
        self._request_id = 0
        self._shutdown_event = threading.Event()

        # SoundとChannelへの参照を保持しておくと、再生途中にPython側の参照が
        # なくなる心配がなく、stop_sound_effect()から確実に停止できる。
        self._sfx_channel = None
        self._sfx_sound = None

        # 素材不足や壊れたWAVはゲーム進行を止めない。その代わり、同じ素材に
        # 対する警告は起動中1回だけ通知し、ログを必要以上に増やさない。
        self._reported_sfx_warnings: set[str] = set()

        # daemon=Trueなので、万一終了処理に到達できなくてもプロセス終了を妨げない。
        # 通常終了時はshutdown()で明示的に停止させる。
        self._generator_thread = threading.Thread(
            target=self._generator_worker,
            daemon=True,
            name="voice-generator",
        )
        self._player_thread = threading.Thread(
            target=self._player_worker,
            daemon=True,
            name="voice-player",
        )
        self._generator_thread.start()
        self._player_thread.start()

    def speak(self, text: str, *, cache_key: str, speaker_id: int) -> None:
        """1文章用の簡便な入口。内部では複数文章対応のspeak_sequenceへ統一。"""
        self.speak_sequence(
            [(text, cache_key)],
            speaker_id=speaker_id,
        )

    def speak_sequence(
        self,
        parts: list[tuple[str, str]],
        *,
        speaker_id: int,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """
        複数の文章を、指定順のまま1つの読み上げ要求として登録する。

        speak()を続けて呼ぶと、後の呼び出しが前の音声を停止する。
        正解後のつなぎ文と次場面のように、両方を連続再生したい場合に使う。
        on_completeは、最後の有効なチャンクが自然に再生終了した場合だけ呼ばれる。
        stop()で中断した場合の完了扱いは、停止を指示した上位側が判断する。
        """
        prepared = self._prepare_chunks(parts)

        if not prepared:
            # 読み上げ可能な文字がなければ、待機側を止めないよう即座に完了扱いにする。
            if on_complete is not None:
                on_complete()
            return

        # 新しい読み上げは前の要求を無効化し、全チャンクへ同じ世代IDを付ける。
        request_id = self._begin_new_request()
        for position, (chunk, cache_key, index) in enumerate(prepared):
            self._generation_queue.put(
                VoiceJob(
                    request_id=request_id,
                    cache_key=f"{cache_key}_{index:03d}",
                    text=chunk,
                    speaker_id=speaker_id,
                    index=index,
                    # 最後の音声だけに通知を持たせることで、複数チャンクでも
                    # 「全文の読み上げ終了」を一度だけ正確に通知できる。
                    on_complete=(
                        on_complete
                        if position == len(prepared) - 1
                        else None
                    ),
                )
            )

    def prepare_first_chunk(
        self,
        parts: list[tuple[str, str]],
        *,
        speaker_id: int,
    ) -> Path | None:
        """
        読み上げ要求の最初のチャンクだけを先行生成してキャッシュする。

        speak_sequence()と同じ分割規則・キャッシュキーを使うため、
        再生開始時は先行生成済みWAVをそのまま利用できる。
        """
        # 本再生と同じ関数で分割しないと、キャッシュキーや先頭文がずれてしまう。
        prepared = self._prepare_chunks(parts)
        if not prepared:
            return None

        first_chunk, cache_key, index = prepared[0]
        client = VoicevoxClient(
            base_url=self.base_url,
            speaker_id=speaker_id,
            cache_dir=self.cache_dir,
        )
        return client.create_or_get_audio(
            first_chunk,
            cache_key=f"{cache_key}_{index:03d}",
        )

    def prefetch(self, text: str, *, cache_key: str, speaker_id: int) -> None:
        """
        再生せず、現在要求が有効な間だけWAVキャッシュを順に作る。

        このメソッド自体は同期処理なので、GUIから直接呼ぶ場合は別スレッドが必要。
        場面変更でrequest_idが変わったら、残りの先読みを打ち切る。
        """
        chunks = split_text_for_voice(text, max_length=80)
        if not chunks:
            return

        request_id = self.current_request_id
        for index, chunk in enumerate(chunks, start=1):
            client = VoicevoxClient(
                base_url=self.base_url,
                speaker_id=speaker_id,
                cache_dir=self.cache_dir,
            )
            try:
                client.create_or_get_audio(
                    chunk,
                    cache_key=f"{cache_key}_{index:03d}",
                )
            except VoicevoxError as exc:
                self._report_error(str(exc))
                return
            # 先読み中に別の読み上げが始まった場合、古い要求へ時間を使わない。
            if request_id != self.current_request_id:
                return

    @staticmethod
    def _prepare_chunks(
        parts: list[tuple[str, str]],
    ) -> list[tuple[str, str, int]]:
        """
        複数文章を、再生順・文章ごとの連番を保ったチャンクへ変換する。

        indexは文章ごとに1から振り直す。cache_keyと組み合わせることで、
        ``scene_1_001`` のように元文章単位で整理された名前になる。
        """
        prepared: list[tuple[str, str, int]] = []
        for text, cache_key in parts:
            chunks = split_text_for_voice(text, max_length=80)
            for index, chunk in enumerate(chunks, start=1):
                prepared.append((chunk, cache_key, index))
        return prepared

    def play_sound_effect(self, wav_path: Path) -> bool:
        """
        指定WAVをVOICEVOXとは独立した専用チャンネルで再生する。

        戻り値は再生を開始できた場合だけTrue。ファイル不足・読み込み失敗・
        音声デバイスの問題は警告へ変換し、ゲーム本体へ例外を伝播させない。
        効果音はassetsから直接読むだけなので、VOICEVOXキャッシュや保存対象へ
        混ざることもない。
        """
        wav_path = Path(wav_path)

        # 新しい結果へ移るときは、前の効果音が長い仮素材でも重ならないよう
        # 先に専用チャンネルだけを止める。対象WAVが不足している場合にも有効。
        self.stop_sound_effect()
        try:
            if not wav_path.is_file():
                raise FileNotFoundError(wav_path)
        except OSError as exc:
            self._report_sfx_warning_once(
                wav_path,
                f"効果音ファイルを確認できません: {wav_path} ({exc})",
            )
            return False

        try:
            # pygameの初期化・読み込み・再生は、VOICEVOX側と同じロックで保護する。
            # ロックするのは短いpygame操作だけで、再生終了までは待たない。
            with self._mixer_lock:
                self._ensure_mixer_initialized_locked()

                # Channel(0)を効果音専用として予約する。VOICEVOXはmusic側なので、
                # 効果音を止めても読み上げの再生キューには触れない。
                required_channels = RESERVED_CHANNEL_COUNT
                if pygame.mixer.get_num_channels() < required_channels:
                    pygame.mixer.set_num_channels(required_channels)
                pygame.mixer.set_reserved(required_channels)

                channel = pygame.mixer.Channel(SFX_CHANNEL_INDEX)
                channel.stop()
                sound = pygame.mixer.Sound(str(wav_path))
                # Sound側へ設定すると、再生開始前から指定音量が確実に反映される。
                sound.set_volume(self._sfx_volume)
                channel.play(sound)
                self._sfx_channel = channel
                self._sfx_sound = sound
            return True
        except Exception as exc:
            self._report_sfx_warning_once(
                wav_path,
                f"効果音を再生できません: {wav_path} ({exc})",
            )
            return False

    def stop_sound_effect(self) -> None:
        """
        現在の効果音だけを停止する。

        VOICEVOXのpygame.mixer.music、request_id、生成・再生キューには触れない。
        「最初から」と終了時に呼ぶことで、前のゲームの音だけが残るのを防ぐ。
        """
        with self._mixer_lock:
            try:
                if pygame.mixer.get_init() and self._sfx_channel is not None:
                    self._sfx_channel.stop()
            except Exception:
                # 終了処理中の音声デバイス解放エラーは、ゲームを止めずに片付ける。
                pass
            finally:
                self._sfx_channel = None
                self._sfx_sound = None

    def set_voice_volume(self, volume: float) -> None:
        """VOICEVOXの現在音量と、これから再生する音声の音量を更新する。"""
        normalized_volume = self._normalize_volume(volume)
        with self._mixer_lock:
            self._voice_volume = normalized_volume
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.set_volume(self._voice_volume)
            except Exception:
                # 音声デバイスの初期化前・終了中でも、保持値の更新は有効にする。
                pass

    def set_sfx_volume(self, volume: float) -> None:
        """効果音の現在音量と、これから再生する効果音の音量を更新する。"""
        normalized_volume = self._normalize_volume(volume)
        with self._mixer_lock:
            self._sfx_volume = normalized_volume
            try:
                if self._sfx_sound is not None:
                    self._sfx_sound.set_volume(self._sfx_volume)
            except Exception:
                # 再生終了とスライダー操作が重なっても、次回再生用の保持値は残す。
                pass

    def stop(self) -> None:
        """
        現在要求を無効化し、待機キューと再生を止める。

        実行中のHTTP通信そのものは強制終了できないが、request_idを進めることで、
        完成後の古いWAVが再生キューへ入るのを防ぐ。生成済みキャッシュは残す。
        """
        # 世代を1つ進めるだけで、ワーカーが持つ古いジョブを無効と判定できる。
        with self._request_lock:
            self._request_id += 1

        # まだ処理されていない古いジョブを両キューから取り除く。
        self._drain_queue(self._generation_queue)
        self._drain_queue(self._playback_queue)

        with self._mixer_lock:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
            except Exception:
                pass

    def shutdown(self) -> None:
        """
        パイプラインを恒久停止し、ワーカーとpygameを終了させる。

        stop()は次の読み上げに備えた一時停止、shutdown()はアプリ終了時だけ使う。
        """
        # stop()はVOICEVOXだけを対象にしているため、効果音は明示的に止める。
        self.stop_sound_effect()
        self.stop()
        self._shutdown_event.set()

        # ブロック中のget()を起こすため、終了番兵Noneをキューへ入れる。
        self._generation_queue.put(None)
        try:
            self._playback_queue.put_nowait(None)
        except queue.Full:
            self._drain_queue(self._playback_queue)
            self._playback_queue.put_nowait(None)

        with self._mixer_lock:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except Exception:
                pass

    @property
    def current_request_id(self) -> int:
        """ロックで保護しながら、現在有効な読み上げ要求IDを返す。"""
        with self._request_lock:
            return self._request_id

    def _begin_new_request(self) -> int:
        """以前の要求を停止し、更新済みIDを新しい要求のIDとして返す。"""
        self.stop()
        with self._request_lock:
            # stop()ですでに+1しているので、その値を今回のIDとして使う。
            return self._request_id

    def _is_current(self, request_id: int) -> bool:
        """ジョブが現在の要求に属し、かつ終了処理前かを判定する。"""
        return request_id == self.current_request_id and not self._shutdown_event.is_set()

    def _generator_worker(self) -> None:
        """生成キューを監視し、有効なテキストジョブをWAVへ変換する。"""
        while not self._shutdown_event.is_set():
            # get()はジョブが来るまで待機するため、空回りでCPUを消費しない。
            job = self._generation_queue.get()
            if job is None:
                self._generation_queue.task_done()
                break

            try:
                # 場面切り替え前の古いジョブは、生成せず破棄する。
                if not self._is_current(job.request_id):
                    continue

                client = VoicevoxClient(
                    base_url=self.base_url,
                    speaker_id=job.speaker_id,
                    cache_dir=self.cache_dir,
                )
                wav_path = client.create_or_get_audio(
                    job.text,
                    cache_key=job.cache_key,
                )

                # 生成中に要求が変わる可能性があるため、完了後にも再確認する。
                if self._is_current(job.request_id):
                    self._put_playback_job(
                        AudioJob(
                            request_id=job.request_id,
                            wav_path=wav_path,
                            on_complete=job.on_complete,
                        )
                    )
            except VoicevoxError as exc:
                if self._is_current(job.request_id):
                    self._report_error(str(exc))
                    self.stop()
            finally:
                # 成功・失敗・continueのどの経路でも、get()と対になるtask_done()を呼ぶ。
                self._generation_queue.task_done()

    def _player_worker(self) -> None:
        """再生キューを監視し、有効なWAVを1件ずつ順番に再生する。"""
        try:
            # mixerは最初の音声再生時に初期化し、その後は終了まで維持する。
            while not self._shutdown_event.is_set():
                job = self._playback_queue.get()
                if job is None:
                    self._playback_queue.task_done()
                    break

                try:
                    # 生成後に場面が変わったWAVも、再生直前に破棄する。
                    if not self._is_current(job.request_id):
                        continue
                    self._play_file(job)
                    # stop()で中断された場合はrequest_idが変わっているため、
                    # 完了通知を呼ばない。最後まで自然に再生できた場合だけ通知する。
                    if self._is_current(job.request_id) and job.on_complete is not None:
                        job.on_complete()
                except Exception as exc:
                    if self._is_current(job.request_id):
                        self._report_error(f"音声再生エラー: {exc}")
                        self.stop()
                finally:
                    self._playback_queue.task_done()
        finally:
            # 予期しない例外でワーカーを抜けても、音声デバイスを解放する。
            with self._mixer_lock:
                try:
                    if pygame.mixer.get_init():
                        pygame.mixer.quit()
                except Exception:
                    pass

    def _play_file(self, job: AudioJob) -> None:
        """
        1つのWAVを読み込み、停止要求を監視しながら再生完了まで待つ。

        pygame操作部分だけをmixer_lockで囲み、待機中はロックを解放する。
        これにより、別スレッドのstop()が再生を中断できる。
        """
        with self._mixer_lock:
            if not self._is_current(job.request_id):
                return
            self._ensure_mixer_initialized_locked()
            pygame.mixer.music.load(str(job.wav_path))
            # mixer.musicの音量はBGM用Soundとは独立しており、VOICEVOXだけへ
            # 適用される。ファイルを切り替えるたび保持値を再適用する。
            pygame.mixer.music.set_volume(self._voice_volume)
            pygame.mixer.music.play()

        # 短い間隔で再生状態と要求IDを確認し、stop()へ素早く反応する。
        while self._is_current(job.request_id):
            with self._mixer_lock:
                busy = bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
            if not busy:
                break
            time.sleep(0.03)

        # Windowsではload中のファイルを削除できない場合があるため、明示的に解放する。
        with self._mixer_lock:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.unload()
            except Exception:
                pass

    @staticmethod
    def _ensure_mixer_initialized_locked() -> None:
        """
        mixer未初期化時だけ、アプリ共通設定で音声デバイスを開く。

        呼び出し側が必ず_mixer_lockを保持する前提の小さな補助メソッド。
        効果音が先でもVOICEVOXが先でも、同じ設定を一度だけ使える。
        """
        ensure_mixer_initialized_locked()

    def _put_playback_job(self, job: AudioJob) -> None:
        """
        再生キューに空きができるまで待ち、有効なジョブだけを登録する。

        timeout付きputで定期的にrequest_idを再確認するため、キュー満杯中でも
        場面変更や終了へ応答できる。
        """
        while self._is_current(job.request_id):
            try:
                self._playback_queue.put(job, timeout=0.1)
                return
            except queue.Full:
                continue

    @staticmethod
    def _normalize_volume(volume: float) -> float:
        """pygameが受け取れる0.0～1.0へ音量を収める。"""
        return max(0.0, min(1.0, float(volume)))

    @staticmethod
    def _drain_queue(target_queue: queue.Queue) -> None:
        """キュー内の待機項目をすべて取り除き、unfinished_tasks数も対応させる。"""
        try:
            while True:
                target_queue.get_nowait()
                target_queue.task_done()
        except queue.Empty:
            pass

    def _report_error(self, message: str) -> None:
        """登録済みコールバックがあれば、音声エラーを上位層へ通知する。"""
        if self.on_error is not None:
            self.on_error(message)

    def _report_sfx_warning_once(self, wav_path: Path, message: str) -> None:
        """同じ効果音ファイルの警告を、アプリ起動中に1回だけ通知する。"""
        warning_key = str(wav_path)
        with self._mixer_lock:
            if warning_key in self._reported_sfx_warnings:
                return
            self._reported_sfx_warnings.add(warning_key)

        if self.on_sfx_warning is not None:
            try:
                self.on_sfx_warning(message)
            except Exception:
                # 警告ログの保存先まで使えない場合でも、効果音の問題だけで
                # ゲーム本体を停止させないことを最優先にする。
                pass


def clean_text_for_voice(text: str) -> str:
    """
    画面表示用の装飾を除き、VOICEVOXが読みやすい文章へ整える。

    元の表示文字列は変更せず、新しい文字列を返す。絵文字などの補助平面文字は
    読みが不安定になりやすいため除去し、空白・改行も整理する。
    """
    # Markdown風の区切り線は無音にせず、文の区切りとして句点へ置換する。
    text = text.replace("---", "。")

    # 見出し・強調・コード用の記号は読み上げない。
    text = re.sub(r"[#*_`]", "", text)

    # 行頭の箇条書き記号を除去する。
    text = re.sub(r"^[\s\-・*]+", "", text, flags=re.MULTILINE)

    # 絵文字を含むUnicode補助平面の文字を除去する。
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)

    # 連続空白と過剰な空行を圧縮し、最後に前後空白を取り除く。
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_text_for_voice(text: str, max_length: int = 80) -> list[str]:
    """
    句読点を優先し、VOICEVOXが早く返せる長さへ文章を分割する。

    分割の優先順位は「文末・改行 -> 読点・空白 -> 固定文字数」。
    できるだけ意味の切れ目を保ちつつ、非常に長い文でも必ず
    ``max_length`` 以下へ分けられる。
    """
    text = clean_text_for_voice(text)
    if not text:
        return []

    # 肯定後読み（?<=）により、句点を手前の文へ残したまま分割する。
    parts = re.split(r"(?<=[。！？!?])|\n+", text)
    chunks: list[str] = []
    current = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # 文末だけで長さを抑えられない場合、次に読点や空白を候補にする。
        sub_parts = [part]
        if len(part) > max_length:
            sub_parts = re.split(r"(?<=[、,])|\s+", part)

        for sub in sub_parts:
            sub = sub.strip()
            if not sub:
                continue

            # 現在の塊へ足すと上限を超える場合、先に現在分を確定する。
            if current and len(current) + len(sub) > max_length:
                chunks.append(current)
                current = ""

            if len(sub) > max_length:
                # 区切りが全くない長文の最終手段として、固定長でスライスする。
                for start in range(0, len(sub), max_length):
                    piece = sub[start:start + max_length].strip()
                    if piece:
                        chunks.append(piece)
            else:
                # 上限内の断片は、次の断片とまとめられるよう一時保持する。
                current += sub

    # ループ終了時に上限未満で残った最後の塊を忘れず追加する。
    if current:
        chunks.append(current)

    return chunks
