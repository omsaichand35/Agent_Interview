from abc import ABC, abstractmethod
import pyttsx3


class TextToSpeech(ABC):

    @abstractmethod
    def synthesize(
        self,
        text: str,
        output_path: str,
    ) -> str:
        pass


class Pyttsx3TTS(TextToSpeech):

    def __init__(self):
        self.engine = pyttsx3.init()

    def synthesize(
        self,
        text: str,
        output_path: str,
    ) -> str:

        if not text.strip():
            raise ValueError(
                "Cannot synthesize empty text."
            )

        self.engine.save_to_file(
            text,
            output_path,
        )

        self.engine.runAndWait()

        return output_path
