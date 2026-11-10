from app.stages.stage4_interview.voice.stt import (
    WhisperSTT,
)


def test_whisper_transcription():

    stt = WhisperSTT(
        model_name="tiny"
    )

    text = stt.transcribe(
        "tests/fixtures/sample.wav"
    )

    assert text.strip()
