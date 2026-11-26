"""Roles come from the channel on stereo recordings, and every fallback says it is a guess."""
import array
import io
import math
import shutil
import wave

import pytest

from app.tasks import speaker_roles as sr

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg missing")
RATE = 16000


def _wav(left, right=None) -> bytes:
    """16-bit WAV. Pass two sample lists for stereo, one for mono."""
    channels = 1 if right is None else 2
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        data = array.array("h")
        for i, l in enumerate(left):
            data.append(l)
            if right is not None:
                data.append(right[i])
        w.writeframes(data.tobytes())
    return buf.getvalue()


def _tone(seconds, amp=8000, freq=440):
    return [int(amp * math.sin(2 * math.pi * freq * i / RATE)) for i in range(int(seconds * RATE))]


def _silence(seconds):
    return [0] * int(seconds * RATE)


class FakeProvider:
    supports_channel_split = True

    def __init__(self, by_audio=None):
        self.calls = []

    def transcribe(self, audio_bytes, filename):
        self.calls.append(audio_bytes)
        # Whatever the diarizer says is ignored for stereo: call it "customer" for every segment.
        return [{"sequence": 0, "speaker_role": "customer", "speaker_id": "spk0", "start_time": 0.0,
                 "end_time": 1.0, "text": f"call {len(self.calls)}", "confidence": 0.9}]


@needs_ffmpeg
def test_probe_counts_channels():
    assert sr.probe_channels(_wav(_tone(1), _tone(1, freq=880))) == 2
    assert sr.probe_channels(_wav(_tone(1))) == 1
    assert sr.probe_channels(b"not audio") == 0


@needs_ffmpeg
def test_two_separate_sides_are_judged_separate():
    left = sr.extract_channel(_wav(_tone(2), _silence(1) + _tone(1, freq=880)), 0)
    right = sr.extract_channel(_wav(_tone(2), _silence(1) + _tone(1, freq=880)), 1)
    assert sr.judge_channels(left, right) == "separate"


@needs_ffmpeg
def test_mono_saved_as_stereo_is_not_treated_as_two_speakers():
    same = _tone(2)
    left, right = (sr.extract_channel(_wav(same, same), i) for i in (0, 1))
    assert sr.judge_channels(left, right) == "identical"


@needs_ffmpeg
def test_only_one_side_recorded_is_flagged():
    left, right = (sr.extract_channel(_wav(_tone(2), _silence(2)), i) for i in (0, 1))
    assert sr.judge_channels(left, right) == "one_silent"


@needs_ffmpeg
def test_stereo_call_gets_roles_from_channels_not_from_diarization():
    # Customer speaks FIRST (right channel), agent answers later (left channel): the case a
    # "speaker 0 = agent" guess gets backwards.
    left = _silence(1) + _tone(1, freq=440)
    right = _tone(1, freq=880) + _silence(1)
    source = _wav(left, right)
    provider = FakeProvider()
    segments, info = sr.transcribe_with_roles(provider, source, b"mono", "c.wav", "left")
    assert info["source"] == "channel"
    assert len(provider.calls) == 2                      # each side transcribed on its own
    assert {s["speaker_role"] for s in segments} == {"agent", "customer"}
    assert {s["speaker_id"] for s in segments} == {"agent_channel", "customer_channel"}
    assert [s["sequence"] for s in segments] == [0, 1]


@needs_ffmpeg
def test_agent_channel_setting_flips_the_mapping():
    source = _wav(_tone(1, freq=440), _silence(0.5) + _tone(1, freq=880))
    left_agent = FakeProvider()
    sr.transcribe_with_roles(left_agent, source, b"mono", "c.wav", "left")
    right_agent = FakeProvider()
    sr.transcribe_with_roles(right_agent, source, b"mono", "c.wav", "right")
    # The first transcribe() call is always the agent's audio, so the two settings send different audio.
    assert left_agent.calls[0] != right_agent.calls[0]
    assert left_agent.calls[0] == right_agent.calls[1]


@needs_ffmpeg
def test_mono_recording_falls_back_and_says_it_is_assumed():
    provider = FakeProvider()
    segments, info = sr.transcribe_with_roles(provider, _wav(_tone(1)), b"mono", "c.wav", "left")
    assert info == {"source": "assumed", "agent_channel": "left", "reason": "mono_recording", "channels": 1}
    assert len(provider.calls) == 1 and segments[0]["speaker_role"] == "customer"


@needs_ffmpeg
def test_stereo_that_is_really_mono_falls_back():
    same = _tone(1)
    _, info = sr.transcribe_with_roles(FakeProvider(), _wav(same, same), b"mono", "c.wav", "left")
    assert info["source"] == "assumed" and info["reason"] == "stereo_not_separated_identical"


def test_provider_without_channel_support_is_never_split():
    class Mock:
        def transcribe(self, audio_bytes, filename):
            return [{"sequence": 0, "speaker_role": "agent", "start_time": 0, "end_time": 1, "text": "hi",
                     "confidence": 1}]

    _, info = sr.transcribe_with_roles(Mock(), b"x", b"y", "c.wav", "left")
    assert info["source"] == "assumed" and info["reason"] == "provider_does_not_split_channels"


def test_merge_orders_by_time_and_drops_empty_text():
    agent = [{"start_time": 5, "end_time": 6, "text": "agent late"}, {"start_time": 0, "end_time": 1, "text": "  "}]
    customer = [{"start_time": 2, "end_time": 3, "text": "customer"}]
    merged = sr.merge_channels(agent, customer)
    assert [(s["speaker_role"], s["sequence"]) for s in merged] == [("customer", 0), ("agent", 1)]


def test_missing_ffprobe_is_reported_not_silently_guessed(monkeypatch):
    monkeypatch.setattr(sr.shutil, "which", lambda name: None)
    _, info = sr.transcribe_with_roles(FakeProvider(), b"x", b"y", "c.wav", "left")
    assert info["source"] == "assumed" and info["reason"] == "ffprobe_missing"


def test_transcribe_stage_runs_end_to_end(db, monkeypatch):
    """The real pipeline stage (not just the helper): a name error here fails EVERY upload."""
    pytest.importorskip("celery")
    from app.models.models import Call, Transcript, TranscriptSegment
    from app.tasks import pipeline

    mono = _wav(_tone(1))
    monkeypatch.setattr(pipeline.minio_client, "download_audio_bytes", lambda path: mono)
    monkeypatch.setattr(pipeline.minio_client, "upload_playback_audio", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_normalize_audio", lambda b: b)
    monkeypatch.setattr(pipeline, "_to_mp3", lambda b: b)
    monkeypatch.setattr(pipeline, "get_stt_provider", lambda: FakeProvider())
    monkeypatch.setattr(pipeline, "_touch_job", lambda *a, **k: None)

    call = Call(original_filename="a.wav", storage_path="x/a.wav")
    db.add(call)
    db.commit()
    segments = pipeline._stage_transcribe(db, call)
    assert segments
    assert call.call_metadata["speaker_roles"]["source"] in {"channel", "assumed", "unknown"}
    assert db.query(Transcript).filter_by(call_id=call.id).count() == 1
    assert db.query(TranscriptSegment).count() == len(segments)
