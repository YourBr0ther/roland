"""Wake word detection for Roland.

Uses OpenWakeWord to detect the "Roland" wake word and activate
the voice command listener.
"""

import asyncio
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from roland.config import get_settings
from roland.utils.logger import get_logger, log_audio_event

logger = get_logger(__name__)

# OpenWakeWord imports - handle gracefully if not installed
try:
    from openwakeword.model import Model as OWWModel

    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    logger.warning("openwakeword_not_installed", message="pip install openwakeword")


class WakeWordDetector:
    """Detects wake word in audio stream.

    Uses OpenWakeWord for efficient, low-latency wake word detection.
    Supports custom wake word models or pretrained models.

    Attributes:
        wake_word: The wake word to detect.
        threshold: Detection confidence threshold.
        model_path: Path to custom wake word model.
        use_pretrained: Whether to use a pretrained model.
    """

    def __init__(
        self,
        wake_word: str = "roland",
        threshold: float = 0.5,
        model_path: Optional[Path] = None,
        use_pretrained: bool = True,
        pretrained_model: str = "hey_jarvis",
    ):
        """Initialize the wake word detector.

        Args:
            wake_word: Wake word to detect.
            threshold: Detection confidence threshold (0.0-1.0).
            model_path: Path to custom ONNX model file.
            use_pretrained: If True, use pretrained model as fallback.
            pretrained_model: Name of pretrained model to use.
        """
        self.wake_word = wake_word
        self.threshold = threshold
        self.model_path = model_path
        self.use_pretrained = use_pretrained
        self.pretrained_model = pretrained_model

        self._model: Optional["OWWModel"] = None
        self._is_listening = False
        self._callback: Optional[Callable[[], None]] = None

        self._initialize_model()

    @classmethod
    def from_config(cls) -> "WakeWordDetector":
        """Create WakeWordDetector from app configuration.

        Returns:
            Configured WakeWordDetector instance.
        """
        settings = get_settings()
        return cls(
            wake_word=settings.wake_word.word,
            threshold=settings.wake_word.threshold,
            model_path=Path(settings.wake_word.model_path)
            if settings.wake_word.model_path
            else None,
            use_pretrained=settings.wake_word.use_pretrained,
            pretrained_model=settings.wake_word.pretrained_model,
        )

    def _initialize_model(self) -> None:
        """Initialize the OpenWakeWord model."""
        if not OPENWAKEWORD_AVAILABLE:
            logger.error("cannot_initialize_wake_word", reason="openwakeword not installed")
            return

        try:
            # Try custom model first
            if self.model_path and self.model_path.exists():
                logger.info("loading_custom_wake_word_model", path=str(self.model_path))
                self._model = self._create_model([str(self.model_path)])
            elif self.use_pretrained:
                # Use pretrained model
                logger.info(
                    "loading_pretrained_wake_word_model",
                    model=self.pretrained_model,
                )
                self._model = self._create_model([self.pretrained_model])
            else:
                logger.warning("no_wake_word_model_available")
                return

            logger.info("wake_word_model_loaded", wake_word=self.wake_word)

        except Exception as e:
            logger.error("wake_word_model_load_failed", error=str(e))
            self._model = None

    def _create_model(self, wakeword_models: list) -> "OWWModel":
        """Create OpenWakeWord model with version-compatible API.

        Prioritizes ONNX runtime since tflite-runtime is often unavailable on Windows.

        Args:
            wakeword_models: List of model names or paths.

        Returns:
            Initialized OWWModel instance.
        """
        # IMPORTANT: Try ONNX first since onnxruntime is installed but tflite-runtime often isn't
        # openwakeword pretrained models (like hey_jarvis) have ONNX versions available

        # Try with explicit ONNX framework (best for cross-platform compatibility)
        try:
            model = OWWModel(
                wakeword_models=wakeword_models,
                inference_framework="onnx",
            )
            logger.info("wake_word_loaded_with_onnx", models=wakeword_models)
            return model
        except TypeError:
            # API doesn't support inference_framework parameter
            logger.debug("onnx_framework_param_not_supported")
        except Exception as e:
            logger.warning("onnx_load_failed", error=str(e)[:100])

        # Try newer API without inference_framework (may use tflite if available)
        try:
            model = OWWModel(wakeword_models=wakeword_models)
            logger.info("wake_word_loaded_default", models=wakeword_models)
            return model
        except Exception as e:
            logger.warning("default_model_load_failed", error=str(e)[:100])

        # Final fallback: load without any models (will use defaults)
        try:
            logger.warning("using_default_wake_word_models")
            return OWWModel()
        except Exception as e:
            logger.error("all_wake_word_load_attempts_failed", error=str(e))
            raise

    @property
    def is_available(self) -> bool:
        """Check if wake word detection is available."""
        return self._model is not None

    def process_audio(self, audio: np.ndarray) -> float:
        """Process audio chunk and return wake word confidence.

        Args:
            audio: Audio samples as numpy array (16-bit or float32).

        Returns:
            Detection confidence score (0.0-1.0).
        """
        if self._model is None:
            return 0.0

        # Ensure correct format (16-bit int)
        if audio.dtype == np.float32:
            audio = (audio * 32767).astype(np.int16)

        # Run prediction
        predictions = self._model.predict(audio)

        # Get the highest confidence for any wake word
        confidence = 0.0
        for model_name, scores in predictions.items():
            if isinstance(scores, (list, np.ndarray)):
                max_score = max(scores) if len(scores) > 0 else 0.0
            else:
                max_score = float(scores)
            confidence = max(confidence, max_score)

        return confidence

    def detect(self, audio: np.ndarray) -> bool:
        """Check if wake word is detected in audio.

        Args:
            audio: Audio samples as numpy array.

        Returns:
            True if wake word detected above threshold.
        """
        confidence = self.process_audio(audio)
        detected = confidence >= self.threshold

        if detected:
            log_audio_event(
                "wake_word_detected",
                wake_word=self.wake_word,
                confidence=confidence,
            )

        return detected

    async def listen(
        self,
        audio_stream,
        on_detected: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Listen for wake word in audio stream.

        Processes audio chunks from the stream until wake word is
        detected or listening is stopped.

        Args:
            audio_stream: Async iterator yielding audio chunks.
            on_detected: Optional callback when wake word detected.

        Returns:
            True if wake word was detected, False if stopped.
        """
        self._is_listening = True
        self._callback = on_detected

        logger.info("wake_word_listening_started", wake_word=self.wake_word)

        try:
            async for audio_chunk in audio_stream:
                if not self._is_listening:
                    break

                if self.detect(audio_chunk):
                    if self._callback:
                        self._callback()
                    return True

        except Exception as e:
            logger.error("wake_word_listening_error", error=str(e))

        finally:
            self._is_listening = False
            logger.info("wake_word_listening_stopped")

        return False

    async def wait_for_activation(
        self,
        audio_pipeline,
        timeout: Optional[float] = None,
    ) -> bool:
        """Wait for wake word activation.

        Convenience method that handles the full flow of listening
        for the wake word using an audio pipeline.

        Args:
            audio_pipeline: AudioPipeline instance for audio input.
            timeout: Optional timeout in seconds.

        Returns:
            True if wake word was detected, False on timeout/stop.
        """
        if not self.is_available:
            logger.warning("wake_word_not_available_falling_back")
            # Fall back to immediate activation (for testing)
            await asyncio.sleep(0.1)
            return True

        audio_stream = audio_pipeline.stream_audio(timeout=timeout)
        return await self.listen(audio_stream)

    def stop(self) -> None:
        """Stop listening for wake word."""
        self._is_listening = False
        log_audio_event("wake_word_listening_stopped")

    def reset(self) -> None:
        """Reset the wake word detector state."""
        if self._model is not None:
            # Reset model's internal buffers
            self._model.reset()
        self._is_listening = False
        logger.info("wake_word_detector_reset")

    def get_status(self) -> dict:
        """Get detector status information.

        Returns:
            Dictionary with status information.
        """
        return {
            "available": self.is_available,
            "wake_word": self.wake_word,
            "threshold": self.threshold,
            "is_listening": self._is_listening,
            "model_type": "custom" if self.model_path else "pretrained",
            "pretrained_model": self.pretrained_model if self.use_pretrained else None,
        }
