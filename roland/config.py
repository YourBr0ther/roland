"""Configuration management for Roland.

Loads configuration from YAML files and environment variables using Pydantic.
"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WakeWordConfig(BaseModel):
    """Wake word detection settings."""

    word: str = "roland"
    model_path: str = "data/wake_word/roland.onnx"
    threshold: float = 0.5
    use_pretrained: bool = True
    pretrained_model: str = "hey_jarvis"


class STTConfig(BaseModel):
    """Speech-to-text settings."""

    model: str = "base.en"
    device: str = "auto"
    compute_type: str = "auto"  # auto detects GPU, falls back to int8 for CPU
    language: str = "en"
    timeout: int = 10


class TTSConfig(BaseModel):
    """Text-to-speech settings."""

    model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    voice_sample: str = "data/voices/reference.wav"
    language: str = "en"
    speed: float = 1.0
    sample_rate: int = 22050


class LLMConfig(BaseModel):
    """LLM settings."""

    provider: str = "ollama"
    model: str = "llama3.2"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.7
    max_tokens: int = 500
    timeout: int = 30


class KeyboardConfig(BaseModel):
    """Keyboard control settings."""

    require_game_focus: bool = True
    game_window_title: str = "Star Citizen"
    press_duration: float = 0.05
    hold_duration: float = 1.0
    combo_delay: float = 0.02


class MacrosConfig(BaseModel):
    """Macro system settings."""

    database_path: str = "data/macros.db"
    max_macros: int = 100


class TrayConfig(BaseModel):
    """System tray settings."""

    show_notifications: bool = True
    start_minimized: bool = False


class AudioConfig(BaseModel):
    """Audio settings."""

    input_device: Optional[int] = None
    output_device: Optional[int] = None
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    play_beep: bool = True
    beep_frequency: int = 800
    beep_duration: float = 0.1


class AppConfig(BaseModel):
    """Application settings."""

    name: str = "Roland"
    version: str = "0.1.0"
    log_level: str = "INFO"
    data_dir: str = "data"


class Settings(BaseSettings):
    """Main settings class that loads from YAML and environment."""

    model_config = SettingsConfigDict(
        env_prefix="ROLAND_",
        env_nested_delimiter="__",
    )

    app: AppConfig = Field(default_factory=AppConfig)
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    keyboard: KeyboardConfig = Field(default_factory=KeyboardConfig)
    macros: MacrosConfig = Field(default_factory=MacrosConfig)
    tray: TrayConfig = Field(default_factory=TrayConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Settings":
        """Load settings from a YAML file.

        Args:
            config_path: Path to config file. If None, uses default paths.

        Returns:
            Settings instance with loaded configuration.
        """
        # Default config paths to check
        default_paths = [
            Path("config/config.yaml"),
            Path("config/default_config.yaml"),
            Path.home() / ".config" / "roland" / "config.yaml",
        ]

        # Find config file
        if config_path and config_path.exists():
            yaml_path = config_path
        else:
            yaml_path = None
            for path in default_paths:
                if path.exists():
                    yaml_path = path
                    break

        # Load YAML if found
        if yaml_path:
            with open(yaml_path) as f:
                yaml_config = yaml.safe_load(f) or {}
        else:
            yaml_config = {}

        # Create settings with YAML values as defaults
        return cls(**yaml_config)

    def get_data_path(self, relative_path: str) -> Path:
        """Get absolute path within data directory.

        Args:
            relative_path: Path relative to data directory.

        Returns:
            Absolute path.
        """
        base = Path(self.app.data_dir)
        return base / relative_path

    def get_voice_sample_path(self) -> Path:
        """Get path to voice sample file."""
        return Path(self.tts.voice_sample)

    def get_wake_word_model_path(self) -> Path:
        """Get path to wake word model."""
        return Path(self.wake_word.model_path)

    def get_macros_db_path(self) -> Path:
        """Get path to macros database."""
        return Path(self.macros.database_path)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance.

    Returns:
        Settings instance (creates one if not exists).
    """
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def reload_settings(config_path: Optional[Path] = None) -> Settings:
    """Reload settings from disk.

    Args:
        config_path: Optional path to config file.

    Returns:
        New settings instance.
    """
    global _settings
    _settings = Settings.load(config_path)
    return _settings
