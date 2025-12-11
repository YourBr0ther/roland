"""Structured logging setup for Roland.

Uses structlog for structured, colorful logging output.
"""

import logging
import sys
from typing import Optional

import structlog
from structlog.types import Processor


def setup_logger(
    level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON format. Otherwise, colorful console output.
    """
    # Set up standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Configure processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_output:
        # JSON output for production/log aggregation
        processors: list[Processor] = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Colorful console output for development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name. If None, uses the calling module's name.

    Returns:
        Configured structlog logger.
    """
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()


class LogContext:
    """Context manager for adding temporary context to logs."""

    def __init__(self, **kwargs):
        """Initialize with context key-value pairs."""
        self.context = kwargs
        self._token = None

    def __enter__(self):
        """Bind context variables."""
        self._token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Unbind context variables."""
        if self._token:
            structlog.contextvars.unbind_contextvars(*self.context.keys())
        return False


def log_command(command: str, user_input: str) -> None:
    """Log a command execution.

    Args:
        command: The command being executed.
        user_input: The user's original voice input.
    """
    logger = get_logger("commands")
    logger.info(
        "command_executed",
        command=command,
        user_input=user_input,
    )


def log_error(error: Exception, context: Optional[dict] = None) -> None:
    """Log an error with context.

    Args:
        error: The exception that occurred.
        context: Optional additional context.
    """
    logger = get_logger("errors")
    logger.error(
        "error_occurred",
        error_type=type(error).__name__,
        error_message=str(error),
        **(context or {}),
    )


def log_audio_event(event: str, **kwargs) -> None:
    """Log an audio-related event.

    Args:
        event: Event name (wake_word_detected, stt_complete, tts_started, etc.).
        **kwargs: Additional event data.
    """
    logger = get_logger("audio")
    logger.info(event, **kwargs)


def log_macro_event(event: str, macro_name: str, **kwargs) -> None:
    """Log a macro-related event.

    Args:
        event: Event name (macro_created, macro_executed, macro_deleted).
        macro_name: Name of the macro.
        **kwargs: Additional event data.
    """
    logger = get_logger("macros")
    logger.info(event, macro_name=macro_name, **kwargs)
