"""
pygame.mixerをアプリ全体で安全に共有するための基盤モジュールです。

VOICEVOX、効果音、BGMは同じ音声デバイスを使用するため、
各機能が個別にpygame.mixerを初期化したり、同時に状態を変更したりすると、
処理が競合する可能性があります。

そのため、このモジュールでは初期化設定・排他ロック・専用チャンネル番号を
一元的に管理しています。

音声の再生先は、次のように分けています。

- pygame.mixer.music: VOICEVOXの読み上げ
- Channel(0): 効果音
- Channel(1), Channel(2): BGMの切り替え用

BGMに2つのチャンネルを使用しているのは、
再生中の曲をフェードアウトしながら、もう一方のチャンネルで
次の曲をフェードインできるようにするためです。
"""

from __future__ import annotations

import threading

import pygame


# VOICEVOXが生成する標準的なWAVへ合わせたアプリ共通のmixer設定。
MIXER_FREQUENCY = 24000
MIXER_SIZE = -16
MIXER_OUTPUT_CHANNELS = 1
MIXER_BUFFER_SIZE = 2048

# 自動割り当てに使われないよう、用途が決まっている先頭3チャンネルを予約する。
SFX_CHANNEL_INDEX = 0
BGM_CHANNEL_INDICES = (1, 2)
RESERVED_CHANNEL_COUNT = max(SFX_CHANNEL_INDEX, *BGM_CHANNEL_INDICES) + 1

# pygame操作はVOICEVOXのワーカースレッドとTkinterのメインスレッドの両方から
# 呼ばれる。1つのRLockを共有すると、短いmixer操作同士が衝突せず、同じ処理内で
# 補助関数を重ねて呼んでもデッドロックしない。
MIXER_LOCK = threading.RLock()


def ensure_mixer_initialized_locked() -> None:
    """
    mixer未初期化時だけ、共通設定で音声デバイスを開く。

    呼び出し側が必ず ``MIXER_LOCK`` を保持している前提の関数である。
    初期化後はBGM・効果音用チャンネル数も確保し、先頭チャンネルを予約する。
    """
    if not pygame.mixer.get_init():
        pygame.mixer.init(
            frequency=MIXER_FREQUENCY,
            size=MIXER_SIZE,
            channels=MIXER_OUTPUT_CHANNELS,
            buffer=MIXER_BUFFER_SIZE,
        )

    if pygame.mixer.get_num_channels() < RESERVED_CHANNEL_COUNT:
        pygame.mixer.set_num_channels(RESERVED_CHANNEL_COUNT)
    pygame.mixer.set_reserved(RESERVED_CHANNEL_COUNT)
