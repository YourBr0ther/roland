"""System tray interface for Roland.

Provides a system tray icon with status indicators and
menu options for controlling the application.
"""

import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

from roland.utils.logger import get_logger

logger = get_logger(__name__)

# pystray import - handle gracefully if not installed
try:
    import pystray
    from pystray import MenuItem as Item

    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    logger.warning("pystray_not_installed", message="pip install pystray")


class TrayStatus(str, Enum):
    """Status states for the tray icon."""

    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"
    DISABLED = "disabled"


# Colors for different states
STATUS_COLORS = {
    TrayStatus.READY: (0, 200, 0),        # Green
    TrayStatus.LISTENING: (0, 150, 255),   # Blue
    TrayStatus.PROCESSING: (255, 200, 0),  # Yellow
    TrayStatus.SPEAKING: (150, 100, 255),  # Purple
    TrayStatus.ERROR: (255, 50, 50),       # Red
    TrayStatus.DISABLED: (128, 128, 128),  # Gray
}


class SystemTray:
    """System tray interface for Roland.

    Displays a tray icon with status colors and provides
    a menu for controlling the application.

    Attributes:
        on_quit: Callback when quit is selected.
        on_toggle: Callback to toggle listening.
        on_settings: Callback to open settings.
        status: Current status state.
    """

    def __init__(
        self,
        on_quit: Optional[Callable[[], None]] = None,
        on_toggle: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_show_macros: Optional[Callable[[], None]] = None,
    ):
        """Initialize the system tray.

        Args:
            on_quit: Callback when quit is selected.
            on_toggle: Callback to toggle listening on/off.
            on_settings: Callback to open settings.
            on_show_macros: Callback to show macro list.
        """
        self.on_quit = on_quit
        self.on_toggle = on_toggle
        self.on_settings = on_settings
        self.on_show_macros = on_show_macros

        self._status = TrayStatus.READY
        self._is_enabled = True
        self._icon: Optional["pystray.Icon"] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def status(self) -> TrayStatus:
        """Get current status."""
        return self._status

    @status.setter
    def status(self, value: TrayStatus) -> None:
        """Set status and update icon."""
        self._status = value
        self._update_icon()

    @property
    def is_enabled(self) -> bool:
        """Check if Roland is enabled."""
        return self._is_enabled

    def _create_icon_image(self, status: TrayStatus, size: int = 64) -> Image.Image:
        """Create an icon image for the given status.

        Args:
            status: Status state for icon color.
            size: Icon size in pixels.

        Returns:
            PIL Image object.
        """
        # Create base image
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Get color for status
        color = STATUS_COLORS.get(status, (128, 128, 128))

        # Draw outer circle (ring)
        margin = size // 8
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color,
        )

        # Draw inner circle (darker center)
        inner_margin = size // 4
        inner_color = tuple(max(0, c - 50) for c in color)
        draw.ellipse(
            [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
            fill=inner_color,
        )

        # Draw "R" in center for Roland
        try:
            # Simple text, may not look great without proper font
            text_color = (255, 255, 255)
            text_pos = (size // 3, size // 4)
            draw.text(text_pos, "R", fill=text_color)
        except Exception:
            pass

        return image

    def _get_menu(self) -> "pystray.Menu":
        """Create the tray menu.

        Returns:
            pystray Menu object.
        """
        if not PYSTRAY_AVAILABLE:
            return None

        items = [
            Item(
                "Roland - Voice Copilot",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            Item(
                "Enabled" if self._is_enabled else "Disabled",
                self._on_toggle_click,
                checked=lambda item: self._is_enabled,
            ),
            Item(
                "Show Macros",
                self._on_macros_click,
            ),
            pystray.Menu.SEPARATOR,
            Item(
                "Settings",
                self._on_settings_click,
            ),
            pystray.Menu.SEPARATOR,
            Item(
                "Quit Roland",
                self._on_quit_click,
            ),
        ]

        return pystray.Menu(*items)

    def _on_toggle_click(self, icon, item) -> None:
        """Handle toggle menu click."""
        self._is_enabled = not self._is_enabled
        if self._is_enabled:
            self.status = TrayStatus.READY
        else:
            self.status = TrayStatus.DISABLED

        if self.on_toggle:
            self.on_toggle()

        # Update menu
        icon.update_menu()
        logger.info("tray_toggle", enabled=self._is_enabled)

    def _on_macros_click(self, icon, item) -> None:
        """Handle show macros click."""
        if self.on_show_macros:
            self.on_show_macros()
        logger.info("tray_show_macros")

    def _on_settings_click(self, icon, item) -> None:
        """Handle settings click."""
        if self.on_settings:
            self.on_settings()
        logger.info("tray_settings")

    def _on_quit_click(self, icon, item) -> None:
        """Handle quit click."""
        logger.info("tray_quit_requested")
        if self.on_quit:
            self.on_quit()
        self.stop()

    def _update_icon(self) -> None:
        """Update the tray icon image."""
        if self._icon is None:
            return

        try:
            new_image = self._create_icon_image(self._status)
            self._icon.icon = new_image
            logger.debug("tray_icon_updated", status=self._status.value)
        except Exception as e:
            logger.error("tray_icon_update_failed", error=str(e))

    def start(self) -> None:
        """Start the system tray in a background thread."""
        if not PYSTRAY_AVAILABLE:
            logger.warning("tray_not_available", reason="pystray not installed")
            return

        if self._thread and self._thread.is_alive():
            logger.warning("tray_already_running")
            return

        def run_tray():
            try:
                image = self._create_icon_image(self._status)
                self._icon = pystray.Icon(
                    name="roland",
                    icon=image,
                    title="Roland - Voice Copilot",
                    menu=self._get_menu(),
                )
                logger.info("tray_started")
                self._icon.run()
            except Exception as e:
                logger.error("tray_run_error", error=str(e))

        self._thread = threading.Thread(target=run_tray, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the system tray."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        logger.info("tray_stopped")

    def set_status(self, status: TrayStatus) -> None:
        """Set the tray status.

        Args:
            status: New status state.
        """
        self.status = status

    def show_notification(self, title: str, message: str) -> None:
        """Show a system notification.

        Args:
            title: Notification title.
            message: Notification message.
        """
        if not PYSTRAY_AVAILABLE or not self._icon:
            return

        try:
            self._icon.notify(message, title)
            logger.debug("tray_notification", title=title)
        except Exception as e:
            logger.error("tray_notification_failed", error=str(e))

    def get_status_text(self) -> str:
        """Get human-readable status text.

        Returns:
            Status description string.
        """
        status_text = {
            TrayStatus.READY: "Ready - Say 'Roland' to activate",
            TrayStatus.LISTENING: "Listening for command...",
            TrayStatus.PROCESSING: "Processing your request...",
            TrayStatus.SPEAKING: "Speaking...",
            TrayStatus.ERROR: "Error - Check logs",
            TrayStatus.DISABLED: "Disabled",
        }
        return status_text.get(self._status, "Unknown")
