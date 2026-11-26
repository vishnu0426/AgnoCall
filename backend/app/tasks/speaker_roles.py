"""
Who is the agent and who is the customer?

A speech-to-text diarizer only says "speaker A" and "speaker B"; it does not know which one works for the
company. Guessing from "who talks first" is wrong on outbound calls, after an IVR or hold music, and after a
transfer, and the QA analysis judges the *agent* by those labels.

When the recording is stereo (the PBX puts each side of the call on its own channel) there is nothing to
guess: each channel is transcribed on its own and the role comes from the channel. That is what this module
does. Anything that cannot be established is labelled honestly (`role_source`) so the UI can warn about it.

role_source values stored on the call (call_metadata["speaker_roles"]["source"]):
  channel      one channel per side, role from the configured channel mapping (reliable)
  assumed      mono / unusable stereo: diarization, first speaker assumed to be the agent (a guess)
  unknown      roles could not be established
"""
import array
import io
import logging
import shutil
import subprocess
import wave

log = logging.getLogger(__name__)

# Below this average level a channel is treated as silent (16-bit samples, max 32768).
SILENT_RMS = 20.0
# Channels whose difference is this small compared with their level carry the same audio (mono saved as stereo).
IDENTICAL_RATIO = 0.05

CHANNEL_INDEX = {"left": 0, "right": 1}


def probe_channels(audio_bytes: bytes) -> int:
    """Number of audio channels in the source file, or 0 if it cannot be read."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
             "-of", "csv=p=0", "pipe:0"],
            input=audio_bytes, capture_output=True, timeout=60,
        )
        return int(proc.stdout.decode().strip().splitlines()[0]) if proc.returncode == 0 else 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0


def extract_channel(audio_bytes: bytes, channel: int) -> bytes:
    """One channel of the source as a 16 kHz mono PCM WAV."""
    proc = subprocess.run(
        ["ffmpeg", "-i", "pipe:0", "-af", f"pan=mono|c0=c{channel}", "-ar", "16000",
         "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
        input=audio_bytes, capture_output=True, timeout=120,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"could not extract channel {channel}: {proc.stderr.decode(errors='replace')[-300:]}")
    return proc.stdout


def _samples(wav_bytes: bytes, step: int = 16) -> array.array:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        data = array.array("h")
        data.frombytes(w.readframes(w.getnframes()))
    return data[::step]


def judge_channels(left_wav: bytes, right_wav: bytes) -> str:
    """'separate' when each channel carries its own side of the call, else why not:
    'identical' (mono saved as stereo), 'one_silent' (only one side recorded) or 'empty'."""
    left, right = _samples(left_wav), _samples(right_wav)
    n = min(len(left), len(right))
    if n == 0:
        return "empty"
    left, right = left[:n], right[:n]
    rms_l = (sum(x * x for x in left) / n) ** 0.5
    rms_r = (sum(x * x for x in right) / n) ** 0.5
    if rms_l < SILENT_RMS and rms_r < SILENT_RMS:
        return "empty"
    if rms_l < SILENT_RMS or rms_r < SILENT_RMS:
        return "one_silent"
    diff = (sum((a - b) ** 2 for a, b in zip(left, right)) / n) ** 0.5
    if diff < IDENTICAL_RATIO * max(rms_l, rms_r):
        return "identical"
    return "separate"


def merge_channels(agent_segments: list[dict], customer_segments: list[dict]) -> list[dict]:
    """Interleave the two channels' segments by start time. Roles come from the channel, never from the
    provider's own diarization."""
    merged = []
    for role, speaker_id, segs in (("agent", "agent_channel", agent_segments),
                                   ("customer", "customer_channel", customer_segments)):
        for s in segs:
            if not str(s.get("text", "")).strip():
                continue
            merged.append({**s, "speaker_role": role, "speaker_id": speaker_id})
    merged.sort(key=lambda s: (s["start_time"], s["end_time"]))
    for i, s in enumerate(merged):
        s["sequence"] = i
    return merged


def transcribe_with_roles(provider, source_audio: bytes, mono_wav: bytes, filename: str,
                          agent_channel: str) -> tuple[list[dict], dict]:
    """Transcribe a call and decide each segment's role. Returns (segments, info) where info is stored on
    the call so the UI can show how the roles were decided."""
    agent_idx = CHANNEL_INDEX.get(agent_channel, 0)
    info: dict = {"source": "assumed", "agent_channel": agent_channel, "reason": None}

    if not getattr(provider, "supports_channel_split", False):
        info["reason"] = "provider_does_not_split_channels"
    elif not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        # Without this check a missing tool would look like "mono recording" and quietly guess the roles.
        info["reason"] = "ffprobe_missing"
        log.warning("ffmpeg/ffprobe not found on PATH: stereo calls cannot be split, speaker roles are guessed")
    else:
        channels = probe_channels(source_audio)
        info["channels"] = channels
        if channels != 2:
            info["reason"] = ("mono_recording" if channels == 1
                              else "could_not_read_channels" if channels == 0 else "unsupported_channel_count")
        else:
            sides = [extract_channel(source_audio, i) for i in (0, 1)]
            verdict = judge_channels(*sides)
            if verdict != "separate":
                info["reason"] = f"stereo_not_separated_{verdict}"
            else:
                agent_wav, customer_wav = sides[agent_idx], sides[1 - agent_idx]
                segments = merge_channels(provider.transcribe(agent_wav, filename),
                                          provider.transcribe(customer_wav, filename))
                info.update(source="channel", reason=None)
                return segments, info

    segments = provider.transcribe(mono_wav, filename)
    if any(s.get("speaker_role") == "unknown" for s in segments):
        info["note"] = "more_than_two_speakers"
    return segments, info
