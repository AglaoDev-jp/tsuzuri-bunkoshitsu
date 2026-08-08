"""
タグに応じて曲を選択し、pygameの専用チャンネルでBGMを管理するモジュールです。

画面遷移やLLMの処理には関与せず、上位層から渡されたBGMタグのみを扱います。
処理を「タグの正規化 → 曲の決定 → 再生」の3段階に分けています。

将来的に1つのタグへ複数の曲を登録する場合も、
`_choose_track_path()` の選択処理を変更することで、
ランダム再生などへ拡張できる構成になっています。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

import pygame

from audio_mixer import (
    BGM_CHANNEL_INDICES,
    MIXER_LOCK,
    ensure_mixer_initialized_locked,
)


class BGMManager:
    """BGMの現在状態、曲選択、ループ再生、フェード切り替えを管理する。"""

    def __init__(
        self,
        *,
        bgm_dir: Path,
        tracks_by_tag: Mapping[str, Sequence[str]],
        volume: float = 0.2,
        fade_ms: int = 800,
        on_warning: Callable[[str], None] | None = None,
        on_track_reference: Callable[[str, Path], None] | None = None,
    ) -> None:
        """素材表と再生設定を受け取り、まだ何も再生していない状態を作る。"""
        self.bgm_dir = Path(bgm_dir)
        # 外部の辞書が後から変更されても再生中の対応表へ影響しないよう、
        # 小文字タグと変更不可tupleへ正規化して保持する。
        self._tracks_by_tag = {
            str(tag).lower().strip(): tuple(str(name) for name in filenames)
            for tag, filenames in tracks_by_tag.items()
        }
        self._volume = self._normalize_volume(volume)
        self._fade_ms = max(0, int(fade_ms))
        self._on_warning = on_warning
        # 実際に解決できたタグと素材パスを上位へ通知する。再生処理とログ保存を
        # 分離しておくことで、このクラスはログファイルの場所を知る必要がない。
        self._on_track_reference = on_track_reference
        self._enabled = True

        self.current_tag: str | None = None
        self.current_track_path: Path | None = None
        self._active_channel_slot: int | None = None

        # Soundへの参照を2チャンネル分保持する。参照が早く破棄されることを防ぎ、
        # 曲を何度切り替えてもメモリ上に全曲が蓄積しない構造にする。
        self._channel_sounds: dict[int, pygame.mixer.Sound | None] = {
            channel_index: None for channel_index in BGM_CHANNEL_INDICES
        }
        self._reported_warnings: set[str] = set()

    def play(self, bgm_tag: str) -> bool:
        """
        タグに対応するBGMを再生し、開始できた場合だけTrueを返す。

        同じタグがすでに再生中なら何もせず、そのままループを継続する。
        異なるタグでは、2つの専用チャンネルを交互に使って、現在曲の
        フェードアウトと次曲のフェードインを同時に行う。
        """
        normalized_tag = self._normalize_tag(bgm_tag)
        if not self._enabled:
            return False

        track_path = self._choose_track_path(normalized_tag)
        if track_path is None:
            # 不明タグや素材不足で前場面の曲だけが残ると、情景と音楽が食い違う。
            # その場合は現在曲を静かに止め、ゲーム本体は通常どおり続行する。
            self.stop()
            return False

        # 同じタグの曲を継続する場合も「今回どの素材を参照したか」は記録できる
        # よう、再生中判定より前に通知する。通知側の失敗でBGMを止めないため、
        # コールバック例外はこのクラス内で吸収する。
        if self._on_track_reference is not None:
            try:
                self._on_track_reference(normalized_tag, track_path)
            except Exception:
                pass

        try:
            with MIXER_LOCK:
                ensure_mixer_initialized_locked()

                # 同じタグかつ同じ曲が現在も鳴っている場合は、再読込も曲頭への
                # 巻き戻しも行わない。Sceneをまたいで自然に演奏が続く。
                if (
                    normalized_tag == self.current_tag
                    and track_path == self.current_track_path
                    and self._active_channel_slot is not None
                    and pygame.mixer.Channel(self._active_channel_slot).get_busy()
                ):
                    return True

                next_channel_slot = self._next_channel_slot()
                next_channel = pygame.mixer.Channel(next_channel_slot)
                next_channel.stop()

                sound = pygame.mixer.Sound(str(track_path))
                sound.set_volume(self._volume)

                # 旧曲は専用チャンネルだけをフェードアウトするため、同時再生中の
                # VOICEVOXや効果音には一切触れない。
                if self._active_channel_slot is not None:
                    pygame.mixer.Channel(self._active_channel_slot).fadeout(
                        self._fade_ms
                    )

                # loops=-1で無限ループ。fade_ms=0の場合もpygameが通常再生として
                # 安全に扱うため、別分岐を作らず設定値をそのまま渡せる。
                next_channel.play(sound, loops=-1, fade_ms=self._fade_ms)
                self._channel_sounds[next_channel_slot] = sound
                self._active_channel_slot = next_channel_slot
                self.current_tag = normalized_tag
                self.current_track_path = track_path
            return True
        except Exception as exc:
            self._warn_once(
                f"play:{track_path}",
                f"BGMを再生できません: {track_path} ({exc})",
            )
            self.stop()
            return False

    def stop(self, *, fade_ms: int | None = None) -> None:
        """BGM専用チャンネルだけを停止し、VOICEVOXと効果音は維持する。"""
        stop_fade_ms = self._fade_ms if fade_ms is None else max(0, int(fade_ms))
        with MIXER_LOCK:
            try:
                if pygame.mixer.get_init():
                    for channel_index in BGM_CHANNEL_INDICES:
                        channel = pygame.mixer.Channel(channel_index)
                        if stop_fade_ms > 0:
                            channel.fadeout(stop_fade_ms)
                        else:
                            channel.stop()
            except Exception:
                # 終了中や音声デバイス解放後の停止失敗は、片付け処理を妨げない。
                pass
            finally:
                self.current_tag = None
                self.current_track_path = None
                self._active_channel_slot = None

    def set_volume(self, volume: float) -> None:
        """現在音量を更新する。将来の音量UIからそのまま呼べる入口。"""
        self._volume = self._normalize_volume(volume)
        with MIXER_LOCK:
            for sound in self._channel_sounds.values():
                if sound is not None:
                    sound.set_volume(self._volume)

    def set_enabled(self, enabled: bool) -> None:
        """BGMの有効状態を更新し、OFFにした場合は現在曲も停止する。"""
        self._enabled = bool(enabled)
        if not self._enabled:
            self.stop()

    def shutdown(self) -> None:
        """アプリ終了時にBGMだけを即時停止し、保持していたSoundを解放する。"""
        self.stop(fade_ms=0)
        self._channel_sounds = {
            channel_index: None for channel_index in BGM_CHANNEL_INDICES
        }

    @staticmethod
    def _normalize_tag(bgm_tag: str) -> str:
        """LLM由来の前後空白や大文字を吸収し、内部タグへそろえる。"""
        return str(bgm_tag).lower().strip()

    def _choose_track_path(self, bgm_tag: str) -> Path | None:
        """
        タグから今回再生する1曲を決定する。

        現在はMP3、OGGなど登録順に存在確認し、最初に見つかった曲を使う。
        将来複数曲へ拡張するときは、存在する候補から前回曲を避けた
        random.choiceなどへ差し替えれば、再生処理を変更せずに済む。
        """
        filenames = self._tracks_by_tag.get(bgm_tag)
        if not filenames:
            self._warn_once(
                f"tag:{bgm_tag}",
                f"未対応のBGMタグです: {bgm_tag or '(空文字)'}",
            )
            return None

        for filename in filenames:
            track_path = self.bgm_dir / filename
            try:
                if track_path.is_file():
                    return track_path
            except OSError:
                # 1候補だけの確認失敗では打ち切らず、同じタグの予備形式を探す。
                continue

        expected_names = ", ".join(filenames)
        self._warn_once(
            f"files:{bgm_tag}",
            f"BGMファイルを確認できません: {self.bgm_dir} / "
            f"候補: {expected_names}",
        )
        return None

    def _next_channel_slot(self) -> int:
        """現在使用していない側のBGMチャンネル番号を返す。"""
        if self._active_channel_slot == BGM_CHANNEL_INDICES[0]:
            return BGM_CHANNEL_INDICES[1]
        return BGM_CHANNEL_INDICES[0]

    @staticmethod
    def _normalize_volume(volume: float) -> float:
        """pygameが受け取れる0.0〜1.0へ音量を収める。"""
        return max(0.0, min(1.0, float(volume)))

    def _warn_once(self, warning_key: str, message: str) -> None:
        """同じ不足素材・不正タグの警告を起動中1回だけ上位へ通知する。"""
        if warning_key in self._reported_warnings:
            return
        self._reported_warnings.add(warning_key)
        if self._on_warning is not None:
            self._on_warning(message)
