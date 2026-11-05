"""Voiceover: Kokoro (natural, ~82M params, runs on the Pi CPU) with Piper as fallback."""

from __future__ import annotations

import logging
import wave
from pathlib import Path

from . import tts

log = logging.getLogger(__name__)
_kokoro = None


def _get_kokoro(cfg: dict):
    global _kokoro
    if _kokoro is None:
        import onnxruntime as rt
        from kokoro_onnx import Kokoro

        v = cfg["voices"]
        # cap threads like everything else (onnxruntime otherwise grabs every core)
        opts = rt.SessionOptions()
        opts.intra_op_num_threads = int(cfg.get("max_threads", 4))
        opts.inter_op_num_threads = 1
        session = rt.InferenceSession(v["kokoro_model"], sess_options=opts, providers=["CPUExecutionProvider"])
        _kokoro = Kokoro.from_session(session, v["kokoro_voices"])
    return _kokoro


def _write_wav(path: Path, samples, rate: int) -> None:
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def synth_lines(cfg: dict, lines: list[str], voice: str, out_wav: Path, speed: float | None = None,
                pause: float = 0.22) -> tuple[Path, list[dict]] | None:
    """Kokoro one line at a time: exact line boundaries, words spread by length inside each line.
    Gives caption timings without running Whisper. None if Kokoro isn't available."""
    v = cfg["voices"]
    if v.get("engine", "kokoro") != "kokoro" or not Path(v["kokoro_model"]).exists():
        return None
    import numpy as np

    try:
        kokoro = _get_kokoro(cfg)
        chunks, words, t, rate = [], [], 0.0, 24000
        for line in lines:
            samples, rate = kokoro.create(line, voice=voice, speed=float(speed or v["speed"]), lang="en-us")
            dur = len(samples) / rate
            tokens = line.split()
            weights = [len(w) + 1 for w in tokens]
            pos = t
            for w, weight in zip(tokens, weights):
                span = dur * weight / sum(weights)
                words.append({"word": w, "start": round(pos, 2), "end": round(pos + span, 2)})
                pos += span
            chunks += [samples, np.zeros(int(pause * rate), dtype=samples.dtype)]
            t += dur + pause
        _write_wav(out_wav, np.concatenate(chunks), rate)
        return out_wav, words
    except Exception as exc:
        log.warning("kokoro line-by-line failed (%s); using whisper timing", exc)
        return None


def synth(cfg: dict, text: str, voice: str, out_wav: Path, speed: float | None = None) -> Path:
    v = cfg["voices"]
    if v.get("engine", "kokoro") == "kokoro" and Path(v["kokoro_model"]).exists():
        try:
            samples, rate = _get_kokoro(cfg).create(text, voice=voice, speed=float(speed or v["speed"]), lang="en-us")
            _write_wav(out_wav, samples, rate)
            return out_wav
        except Exception as exc:
            log.warning("kokoro failed (%s); falling back to piper", exc)
    result = tts.speak({"audio": {**cfg["audio"], "narration": True}}, text, out_wav)
    if result is None:
        raise RuntimeError("no TTS engine available (install kokoro-onnx or piper)")
    return result
