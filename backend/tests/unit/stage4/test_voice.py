from app.stages.stage4_interview.voice.voice_service import (
    VoiceService,
)


class MockSTT:

    def transcribe(self, audio_path):

        return (
            "I built a distributed backend "
            "using Python and Docker."
        )


class MockTTS:

    def synthesize(self, text, output_path):

        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as file:

            file.write(text)

        return output_path


def test_voice_service_transcription():

    service = VoiceService(
        stt=MockSTT(),
        tts=MockTTS(),
    )

    text = service.transcribe(
        "fake_audio.wav"
    )

    assert "distributed backend" in text


def test_voice_service_tts(tmp_path):

    service = VoiceService(
        stt=MockSTT(),
        tts=MockTTS(),
    )

    output = tmp_path / "question.txt"

    result = service.speak(
        "Tell me about your backend experience.",
        str(output),
    )

    assert result == str(output)
    assert output.exists()
