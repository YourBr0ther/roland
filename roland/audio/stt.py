"""Speech-to-text transcription for Roland.

Uses RealtimeSTT with Whisper for fast, accurate transcription
of voice commands.
"""

import asyncio
from typing import Optional

import numpy as np

from roland.config import get_settings
from roland.utils.logger import get_logger, log_audio_event

logger = get_logger(__name__)

# RealtimeSTT imports - handle gracefully if not installed
try:
    from RealtimeSTT import AudioToTextRecorder

    REALTIMESTT_AVAILABLE = True
except ImportError:
    REALTIMESTT_AVAILABLE = False
    logger.warning("realtimestt_not_installed", message="pip install RealtimeSTT")


class SpeechToText:
    """Converts speech to text using Whisper.

    Uses RealtimeSTT for efficient real-time transcription with
    voice activity detection and automatic endpoint detection.

    Attributes:
        model: Whisper model size.
        device: Processing device (cpu/cuda/auto).
        language: Language code for transcription.
        timeout: Maximum listening time in seconds.
    """

    def __init__(
        self,
        model: str = "base.en",
        device: str = "auto",
        compute_type: str = "float16",
        language: str = "en",
        timeout: int = 10,
    ):
        """Initialize the speech-to-text engine.

        Args:
            model: Whisper model size (tiny.en, base.en, small.en, medium.en, large-v3).
            device: Processing device (auto, cpu, cuda).
            compute_type: Computation type (float16, float32, int8).
            language: Language code.
            timeout: Maximum listening time in seconds.
        """
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.timeout = timeout

        self._recorder: Optional["AudioToTextRecorder"] = None
        self._is_transcribing = False
        self._last_result: Optional[str] = None

    @classmethod
    def from_config(cls) -> "SpeechToText":
        """Create SpeechToText from app configuration.

        Returns:
            Configured SpeechToText instance.
        """
        settings = get_settings()
        return cls(
            model=settings.stt.model,
            device=settings.stt.device,
            compute_type=settings.stt.compute_type,
            language=settings.stt.language,
            timeout=settings.stt.timeout,
        )

    def _initialize_recorder(self) -> None:
        """Initialize the RealtimeSTT recorder."""
        if not REALTIMESTT_AVAILABLE:
            logger.error("cannot_initialize_stt", reason="RealtimeSTT not installed")
            return

        if self._recorder is not None:
            return

        try:
            logger.info(
                "initializing_stt",
                model=self.model,
                device=self.device,
            )

            self._recorder = AudioToTextRecorder(
                model=self.model,
                language=self.language,
                compute_type=self.compute_type,
                device=self.device if self.device != "auto" else None,
                spinner=False,
                silero_sensitivity=0.4,
                webrtc_sensitivity=2,
                post_speech_silence_duration=0.6,
                min_length_of_recording=0.5,
                min_gap_between_recordings=0.0,
                enable_realtime_transcription=False,
            )

            logger.info("stt_initialized", model=self.model)

        except Exception as e:
            logger.error("stt_initialization_failed", error=str(e))
            self._recorder = None

    @property
    def is_available(self) -> bool:
        """Check if STT is available."""
        return REALTIMESTT_AVAILABLE

    async def transcribe(self, timeout: Optional[int] = None) -> Optional[str]:
        """Listen and transcribe speech.

        Listens for speech using the microphone, waits for the user
        to finish speaking, and returns the transcription.

        Args:
            timeout: Optional timeout override in seconds.

        Returns:
            Transcribed text or None if no speech detected.
        """
        if not REALTIMESTT_AVAILABLE:
            logger.error("stt_not_available")
            return None

        self._initialize_recorder()

        if self._recorder is None:
            return None

        self._is_transcribing = True
        self._last_result = None
        listen_timeout = timeout or self.timeout

        log_audio_event("stt_listening_started", timeout=listen_timeout)

        try:
            # RealtimeSTT uses blocking calls, run in executor
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._recorder.text),
                timeout=listen_timeout,
            )

            if result and result.strip():
                self._last_result = result.strip()
                log_audio_event(
                    "stt_transcription_complete",
                    text=self._last_result[:100],
                    length=len(self._last_result),
                )
                return self._last_result
            else:
                log_audio_event("stt_no_speech_detected")
                return None

        except asyncio.TimeoutError:
            log_audio_event("stt_timeout", timeout=listen_timeout)
            return None
        except Exception as e:
            logger.error("stt_error", error=str(e))
            return None
        finally:
            self._is_transcribing = False

    async def transcribe_audio(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe pre-recorded audio.

        Args:
            audio: Audio samples as numpy array.
            sample_rate: Audio sample rate.

        Returns:
            Transcribed text or None on failure.
        """
        if not REALTIMESTT_AVAILABLE:
            logger.error("stt_not_available")
            return None

        # For pre-recorded audio, use faster-whisper directly
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                self.model,
                device=self.device if self.device != "auto" else "auto",
                compute_type=self.compute_type,
            )

            # Ensure audio is float32
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # Transcribe
            segments, info = model.transcribe(audio, language=self.language)
            text = " ".join([segment.text for segment in segments]).strip()

            if text:
                log_audio_event(
                    "stt_transcription_complete",
                    text=text[:100],
                    length=len(text),
                )
                return text
            return None

        except ImportError:
            logger.error("faster_whisper_not_available")
            return None
        except Exception as e:
            logger.error("stt_transcribe_audio_error", error=str(e))
            return None

    def stop(self) -> None:
        """Stop ongoing transcription."""
        self._is_transcribing = False
        if self._recorder:
            try:
                self._recorder.abort()
            except Exception:
                pass
        log_audio_event("stt_stopped")

    @property
    def is_transcribing(self) -> bool:
        """Check if currently transcribing."""
        return self._is_transcribing

    @property
    def last_result(self) -> Optional[str]:
        """Get the last transcription result."""
        return self._last_result

    def get_status(self) -> dict:
        """Get STT status information.

        Returns:
            Dictionary with status information.
        """
        return {
            "available": self.is_available,
            "model": self.model,
            "device": self.device,
            "language": self.language,
            "is_transcribing": self._is_transcribing,
            "initialized": self._recorder is not None,
        }

    def shutdown(self) -> None:
        """Shutdown the STT engine and free resources."""
        self.stop()
        if self._recorder:
            try:
                self._recorder.shutdown()
            except Exception:
                pass
            self._recorder = None
        logger.info("stt_shutdown_complete")
