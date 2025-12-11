"""Text-to-speech synthesis for Roland.

Uses Coqui TTS with XTTS for high-quality voice cloning
to create the JARVIS-style AI voice.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from roland.config import get_settings
from roland.utils.logger import get_logger, log_audio_event

logger = get_logger(__name__)

# TTS imports - handle gracefully if not installed
try:
    from TTS.api import TTS

    COQUI_TTS_AVAILABLE = True
except ImportError:
    COQUI_TTS_AVAILABLE = False
    logger.warning("coqui_tts_not_installed", message="pip install TTS")


class TextToSpeech:
    """Synthesizes speech from text using voice cloning.

    Uses Coqui XTTS for zero-shot voice cloning, allowing
    Roland to speak with a custom JARVIS-style voice.

    Attributes:
        model_name: TTS model identifier.
        voice_sample: Path to reference audio for voice cloning.
        language: Language code for synthesis.
        speed: Speech speed multiplier.
    """

    def __init__(
        self,
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        voice_sample: Optional[Path] = None,
        language: str = "en",
        speed: float = 1.0,
        sample_rate: int = 22050,
    ):
        """Initialize the TTS engine.

        Args:
            model_name: Coqui TTS model name.
            voice_sample: Path to reference voice WAV file.
            language: Language code (en, es, fr, etc.).
            speed: Speech speed multiplier (0.5-2.0).
            sample_rate: Output audio sample rate.
        """
        self.model_name = model_name
        self.voice_sample = voice_sample
        self.language = language
        self.speed = speed
        self.sample_rate = sample_rate

        self._tts: Optional["TTS"] = None
        self._is_speaking = False

    @classmethod
    def from_config(cls) -> "TextToSpeech":
        """Create TextToSpeech from app configuration.

        Returns:
            Configured TextToSpeech instance.
        """
        settings = get_settings()
        voice_path = Path(settings.tts.voice_sample)
        return cls(
            model_name=settings.tts.model,
            voice_sample=voice_path if voice_path.exists() else None,
            language=settings.tts.language,
            speed=settings.tts.speed,
            sample_rate=settings.tts.sample_rate,
        )

    def _initialize_tts(self) -> None:
        """Initialize the Coqui TTS model."""
        if not COQUI_TTS_AVAILABLE:
            logger.error("cannot_initialize_tts", reason="Coqui TTS not installed")
            return

        if self._tts is not None:
            return

        try:
            logger.info(
                "initializing_tts",
                model=self.model_name,
            )

            self._tts = TTS(model_name=self.model_name)

            # Check if GPU is available
            if hasattr(self._tts, "to"):
                try:
                    import torch

                    if torch.cuda.is_available():
                        self._tts.to("cuda")
                        logger.info("tts_using_gpu")
                except ImportError:
                    pass

            logger.info("tts_initialized", model=self.model_name)

        except Exception as e:
            logger.error("tts_initialization_failed", error=str(e))
            self._tts = None

    @property
    def is_available(self) -> bool:
        """Check if TTS is available."""
        return COQUI_TTS_AVAILABLE

    @property
    def has_voice_sample(self) -> bool:
        """Check if a voice sample is configured and exists."""
        return self.voice_sample is not None and self.voice_sample.exists()

    async def synthesize(self, text: str) -> Optional[np.ndarray]:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize.

        Returns:
            Audio samples as numpy array, or None on failure.
        """
        if not COQUI_TTS_AVAILABLE:
            logger.error("tts_not_available")
            return None

        if not text or not text.strip():
            logger.warning("tts_empty_text")
            return None

        self._initialize_tts()

        if self._tts is None:
            return None

        self._is_speaking = True
        log_audio_event("tts_synthesis_started", text_length=len(text))

        try:
            loop = asyncio.get_event_loop()
            audio = None

            if self.has_voice_sample:
                # Try voice cloning with reference audio
                try:
                    audio = await loop.run_in_executor(
                        None,
                        lambda: self._tts.tts(
                            text=text,
                            speaker_wav=str(self.voice_sample),
                            language=self.language,
                        ),
                    )
                except Exception as clone_err:
                    # Voice cloning failed (e.g., torchcodec not installed)
                    logger.warning(
                        "tts_voice_cloning_failed_using_default",
                        error=str(clone_err)[:100],
                    )
                    audio = None

            if audio is None:
                # Use default voice (no cloning)
                if self.has_voice_sample:
                    logger.warning("tts_fallback_to_default_voice")
                audio = await loop.run_in_executor(
                    None,
                    lambda: self._tts.tts(text=text),
                )

            # Convert to numpy array
            audio_array = np.array(audio, dtype=np.float32)

            log_audio_event(
                "tts_synthesis_complete",
                text_length=len(text),
                audio_length=len(audio_array),
            )

            return audio_array

        except Exception as e:
            logger.error("tts_synthesis_error", error=str(e), text=text[:50])
            return None
        finally:
            self._is_speaking = False

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech and save to file.

        Args:
            text: Text to synthesize.
            output_path: Output WAV file path.

        Returns:
            True if successful, False otherwise.
        """
        if not COQUI_TTS_AVAILABLE:
            return False

        if not text or not text.strip():
            return False

        self._initialize_tts()

        if self._tts is None:
            return False

        self._is_speaking = True

        try:
            loop = asyncio.get_event_loop()

            if self.has_voice_sample:
                await loop.run_in_executor(
                    None,
                    lambda: self._tts.tts_to_file(
                        text=text,
                        speaker_wav=str(self.voice_sample),
                        language=self.language,
                        file_path=str(output_path),
                    ),
                )
            else:
                await loop.run_in_executor(
                    None,
                    lambda: self._tts.tts_to_file(
                        text=text,
                        file_path=str(output_path),
                    ),
                )

            logger.info("tts_file_saved", path=str(output_path))
            return True

        except Exception as e:
            logger.error("tts_file_save_error", error=str(e))
            return False
        finally:
            self._is_speaking = False

    def set_voice_sample(self, voice_sample: Path) -> bool:
        """Set or update the voice sample for cloning.

        Args:
            voice_sample: Path to reference WAV file.

        Returns:
            True if sample is valid and set.
        """
        if not voice_sample.exists():
            logger.error("voice_sample_not_found", path=str(voice_sample))
            return False

        # Validate it's a WAV file
        if voice_sample.suffix.lower() not in [".wav", ".mp3", ".flac"]:
            logger.warning("voice_sample_format", format=voice_sample.suffix)

        self.voice_sample = voice_sample
        logger.info("voice_sample_set", path=str(voice_sample))
        return True

    @property
    def is_speaking(self) -> bool:
        """Check if currently synthesizing speech."""
        return self._is_speaking

    def get_status(self) -> dict:
        """Get TTS status information.

        Returns:
            Dictionary with status information.
        """
        return {
            "available": self.is_available,
            "model": self.model_name,
            "language": self.language,
            "speed": self.speed,
            "has_voice_sample": self.has_voice_sample,
            "voice_sample_path": str(self.voice_sample) if self.voice_sample else None,
            "is_speaking": self._is_speaking,
            "initialized": self._tts is not None,
        }

    def list_available_models(self) -> list[str]:
        """List available TTS models.

        Returns:
            List of model names.
        """
        if not COQUI_TTS_AVAILABLE:
            return []

        try:
            from TTS.utils.manage import ModelManager

            manager = ModelManager()
            return list(manager.list_models())
        except Exception:
            return [
                "tts_models/multilingual/multi-dataset/xtts_v2",
                "tts_models/en/ljspeech/tacotron2-DDC",
                "tts_models/en/vctk/vits",
            ]

    def shutdown(self) -> None:
        """Shutdown TTS engine and free resources."""
        self._is_speaking = False
        self._tts = None
        logger.info("tts_shutdown_complete")
