"""Audio I/O pipeline management for Roland.

Handles microphone input, speaker output, and audio stream coordination.
"""

import asyncio
import wave
from io import BytesIO
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

import numpy as np
import sounddevice as sd

from roland.config import get_settings
from roland.utils.logger import get_logger, log_audio_event

logger = get_logger(__name__)


class AudioPipeline:
    """Manages audio input and output streams.

    Provides methods for capturing microphone audio and playing
    synthesized speech through speakers.

    Attributes:
        sample_rate: Audio sample rate in Hz.
        channels: Number of audio channels.
        chunk_size: Audio buffer chunk size.
        input_device: Input device index.
        output_device: Output device index.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
    ):
        """Initialize the audio pipeline.

        Args:
            sample_rate: Audio sample rate in Hz.
            channels: Number of audio channels (1 = mono).
            chunk_size: Size of audio buffer chunks.
            input_device: Input device index (None = default).
            output_device: Output device index (None = default).
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.input_device = input_device
        self.output_device = output_device

        self._is_recording = False
        self._is_playing = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

    @classmethod
    def from_config(cls) -> "AudioPipeline":
        """Create AudioPipeline from app configuration.

        Returns:
            Configured AudioPipeline instance.
        """
        settings = get_settings()
        return cls(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
            chunk_size=settings.audio.chunk_size,
            input_device=settings.audio.input_device,
            output_device=settings.audio.output_device,
        )

    def list_devices(self) -> dict:
        """List available audio devices.

        Returns:
            Dictionary with 'input' and 'output' device lists.
        """
        devices = sd.query_devices()
        input_devices = []
        output_devices = []

        for i, device in enumerate(devices):
            device_info = {
                "index": i,
                "name": device["name"],
                "sample_rate": device["default_samplerate"],
            }
            if device["max_input_channels"] > 0:
                input_devices.append(device_info)
            if device["max_output_channels"] > 0:
                output_devices.append(device_info)

        return {"input": input_devices, "output": output_devices}

    async def record_audio(
        self,
        duration: float,
        callback: Optional[Callable[[np.ndarray], None]] = None,
    ) -> np.ndarray:
        """Record audio from microphone for a fixed duration.

        Args:
            duration: Recording duration in seconds.
            callback: Optional callback for each audio chunk.

        Returns:
            Numpy array of recorded audio samples.
        """
        log_audio_event("recording_started", duration=duration)
        self._is_recording = True

        frames = int(duration * self.sample_rate)
        recording = sd.rec(
            frames,
            samplerate=self.sample_rate,
            channels=self.channels,
            device=self.input_device,
            dtype=np.float32,
        )

        # Wait for recording to complete
        await asyncio.get_event_loop().run_in_executor(None, sd.wait)

        self._is_recording = False
        log_audio_event("recording_complete", samples=len(recording))

        return recording.flatten()

    async def stream_audio(
        self,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[np.ndarray]:
        """Stream audio chunks from microphone.

        Yields audio chunks until stopped or timeout reached.

        Args:
            timeout: Optional timeout in seconds.

        Yields:
            Numpy arrays of audio chunks.
        """
        log_audio_event("stream_started")
        self._is_recording = True
        start_time = asyncio.get_event_loop().time()

        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning("audio_stream_status", status=str(status))
            # Put audio data in queue
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(
                self._audio_queue.put_nowait,
                indata.copy().tobytes(),
            )

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            device=self.input_device,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=audio_callback,
        ):
            while self._is_recording:
                try:
                    # Check timeout
                    if timeout:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        if elapsed >= timeout:
                            logger.info("stream_timeout_reached")
                            break

                    # Get audio chunk with timeout
                    audio_bytes = await asyncio.wait_for(
                        self._audio_queue.get(),
                        timeout=0.5,
                    )
                    audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
                    yield audio_array

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("stream_error", error=str(e))
                    break

        self._is_recording = False
        log_audio_event("stream_stopped")

    def stop_recording(self) -> None:
        """Stop any ongoing recording."""
        self._is_recording = False
        log_audio_event("recording_stopped")

    async def play_audio(
        self,
        audio: np.ndarray,
        sample_rate: Optional[int] = None,
        blocking: bool = True,
    ) -> None:
        """Play audio through speakers.

        Args:
            audio: Audio samples as numpy array.
            sample_rate: Sample rate (uses pipeline default if None).
            blocking: If True, wait for playback to complete.
        """
        rate = sample_rate or self.sample_rate
        log_audio_event("playback_started", samples=len(audio), sample_rate=rate)
        self._is_playing = True

        try:
            sd.play(audio, rate, device=self.output_device)
            if blocking:
                await asyncio.get_event_loop().run_in_executor(None, sd.wait)
        finally:
            self._is_playing = False
            log_audio_event("playback_complete")

    async def play_file(self, file_path: Path, blocking: bool = True) -> None:
        """Play audio from a WAV file.

        Args:
            file_path: Path to WAV file.
            blocking: If True, wait for playback to complete.
        """
        with wave.open(str(file_path), "rb") as wf:
            sample_rate = wf.getframerate()
            audio_bytes = wf.readframes(wf.getnframes())
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            audio = audio / 32768.0  # Normalize to [-1, 1]

        await self.play_audio(audio, sample_rate, blocking)

    async def play_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int = 22050,
        blocking: bool = True,
    ) -> None:
        """Play audio from raw bytes.

        Args:
            audio_bytes: Raw audio bytes (float32 or int16).
            sample_rate: Sample rate of the audio.
            blocking: If True, wait for playback to complete.
        """
        # Try to detect format from byte length
        try:
            # Try float32 first
            audio = np.frombuffer(audio_bytes, dtype=np.float32)
        except Exception:
            # Fall back to int16
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            audio = audio / 32768.0

        await self.play_audio(audio, sample_rate, blocking)

    def stop_playback(self) -> None:
        """Stop any ongoing audio playback."""
        sd.stop()
        self._is_playing = False
        log_audio_event("playback_stopped")

    async def play_beep(
        self,
        frequency: int = 800,
        duration: float = 0.1,
        volume: float = 0.3,
    ) -> None:
        """Play a simple acknowledgment beep.

        Args:
            frequency: Beep frequency in Hz.
            duration: Beep duration in seconds.
            volume: Volume (0.0 to 1.0).
        """
        # Generate sine wave
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        beep = np.sin(2 * np.pi * frequency * t) * volume

        # Apply fade in/out to avoid clicks
        fade_samples = int(0.01 * self.sample_rate)
        beep[:fade_samples] *= np.linspace(0, 1, fade_samples)
        beep[-fade_samples:] *= np.linspace(1, 0, fade_samples)

        await self.play_audio(beep.astype(np.float32), blocking=True)

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording

    @property
    def is_playing(self) -> bool:
        """Check if currently playing audio."""
        return self._is_playing

    def cleanup(self) -> None:
        """Clean up audio resources."""
        self.stop_recording()
        self.stop_playback()
        # Clear queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("audio_pipeline_cleanup_complete")
