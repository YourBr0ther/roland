"""Audio processing modules for Roland.

Includes:
- pipeline: Audio I/O stream management
- wake_word: Wake word detection ("Roland")
- stt: Speech-to-text transcription
- tts: Text-to-speech synthesis (JARVIS voice)
"""

from roland.audio.pipeline import AudioPipeline
from roland.audio.wake_word import WakeWordDetector
from roland.audio.stt import SpeechToText
from roland.audio.tts import TextToSpeech

__all__ = ["AudioPipeline", "WakeWordDetector", "SpeechToText", "TextToSpeech"]
