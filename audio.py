"""用 numpy 现场合成音效，不依赖任何音频素材文件。"""

from __future__ import annotations

import numpy as np
import pygame

import config as C


class Audio:
    def __init__(self, sample_rate: int = 44100):
        self.ok = False
        self.muted = False
        self.sr = sample_rate
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            pygame.mixer.init(frequency=sample_rate, size=-16, channels=1, buffer=512)
            self.ok = True
        except Exception:
            return
        self._build()

    # -- 合成小工具 ----------------------------------------------------

    def _pack(self, data: np.ndarray, gain: float = 1.0):
        data = np.clip(data * gain, -1.0, 1.0)
        pcm = (data * 32767.0).astype(np.int16)
        init = pygame.mixer.get_init()
        ch = init[2] if init else 1
        # 单声道要一维数组，立体声要 (n, 2)
        arr = pcm.reshape(-1) if ch == 1 else np.repeat(pcm.reshape(-1, 1), ch, axis=1)
        return pygame.sndarray.make_sound(np.ascontiguousarray(arr))

    def _env(self, n: int, decay: float):
        # 用实际采样率，别硬编码 44100 —— 换采样率时包络长度才不会静默出错
        t = np.arange(n) / float(self.sr)
        return np.exp(-t * decay)

    @staticmethod
    def _noise(n: int, smooth: int = 3):
        x = np.random.uniform(-1.0, 1.0, n)
        if smooth > 1:
            x = np.convolve(x, np.ones(smooth) / smooth, mode="same")
        return x / (np.max(np.abs(x)) + 1e-9)

    # -- 音色 ----------------------------------------------------------

    def _build(self):
        sr = self.sr

        # 枪声：噪声爆音 + 低频「咚」
        n = int(sr * 0.13)
        t = np.arange(n) / sr
        shot = self._noise(n, 4) * self._env(n, 46.0) * 0.85
        shot += np.sin(2 * np.pi * 95 * t) * self._env(n, 70.0) * 0.45
        self.sounds["shot"] = self._pack(shot, 0.42)

        # 命中：短促双音
        n = int(sr * 0.075)
        t = np.arange(n) / sr
        hit = (np.sin(2 * np.pi * 880 * t) + 0.6 * np.sin(2 * np.pi * 1320 * t))
        self.sounds["hit"] = self._pack(hit * self._env(n, 55.0), 0.30)

        # 爆头：更高更亮
        n = int(sr * 0.10)
        t = np.arange(n) / sr
        head = (np.sin(2 * np.pi * 1500 * t) + 0.7 * np.sin(2 * np.pi * 2250 * t))
        self.sounds["head"] = self._pack(head * self._env(n, 42.0), 0.34)

        # 断连：低沉短音
        n = int(sr * 0.16)
        t = np.arange(n) / sr
        miss = np.sin(2 * np.pi * 180 * t) * self._env(n, 26.0)
        self.sounds["miss"] = self._pack(miss, 0.18)

        # 靶子刷新：轻点
        n = int(sr * 0.06)
        t = np.arange(n) / sr
        self.sounds["spawn"] = self._pack(
            np.sin(2 * np.pi * 620 * t) * self._env(n, 90.0), 0.10)

    # -- 播放 ----------------------------------------------------------

    def play(self, name: str):
        if not self.ok or self.muted:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            snd.play()

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted
