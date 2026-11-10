class VoiceService:

    def __init__(
        self,
        stt,
        tts,
    ):
        self.stt = stt
        self.tts = tts

    def transcribe(
        self,
        audio_path: str,
    ) -> str:

        return self.stt.transcribe(
            audio_path
        )

    def speak(
        self,
        text: str,
        output_path: str,
    ) -> str:

        return self.tts.synthesize(
            text,
            output_path,
        )
