"""Roland - Star Citizen Voice Copilot.

Main application entry point and orchestration.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

from roland import __version__
from roland.audio.pipeline import AudioPipeline
from roland.audio.stt import SpeechToText
from roland.audio.tts import TextToSpeech
from roland.audio.wake_word import WakeWordDetector
from roland.config import Settings, get_settings, reload_settings
from roland.keyboard.executor import KeyboardExecutor
from roland.keyboard.keybinds import KeybindManager
from roland.llm.context import ContextManager
from roland.llm.interpreter import CommandInterpreter, CommandType
from roland.llm.ollama_client import OllamaClient
from roland.macros.manager import MacroManager
from roland.ui.tray import SystemTray, TrayStatus
from roland.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)


class Roland:
    """Main Roland application class.

    Orchestrates all components including audio input/output,
    wake word detection, speech recognition, LLM processing,
    keyboard execution, and macro management.

    Attributes:
        settings: Application settings.
        running: Whether the main loop is running.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize Roland.

        Args:
            config_path: Optional path to configuration file.
        """
        # Load settings
        if config_path:
            self.settings = reload_settings(config_path)
        else:
            self.settings = get_settings()

        # Setup logging
        setup_logger(level=self.settings.app.log_level)

        logger.info(
            "roland_initializing",
            version=__version__,
            config_path=str(config_path) if config_path else "default",
        )

        # Initialize components
        self.audio = AudioPipeline.from_config()
        self.wake_word = WakeWordDetector.from_config()
        self.stt = SpeechToText.from_config()
        self.tts = TextToSpeech.from_config()
        self.llm = OllamaClient.from_config()
        self.interpreter = CommandInterpreter()
        self.context = ContextManager()
        self.keyboard = KeyboardExecutor(
            require_focus=self.settings.keyboard.require_game_focus,
            game_window_title=self.settings.keyboard.game_window_title,
            press_duration=self.settings.keyboard.press_duration,
            hold_duration=self.settings.keyboard.hold_duration,
        )
        self.keybinds = KeybindManager()
        self.macros = MacroManager()

        # System tray
        self.tray = SystemTray(
            on_quit=self._on_quit,
            on_toggle=self._on_toggle,
            on_show_macros=self._on_show_macros,
        )

        # State
        self.running = False
        self._enabled = True

    async def run(self) -> None:
        """Run the main application loop."""
        self.running = True

        # Start system tray
        self.tray.start()
        self.tray.set_status(TrayStatus.READY)

        # Startup announcement
        await self._speak("Roland online and ready, Commander. Say my name when you need me.")

        logger.info("roland_started", wake_word=self.settings.wake_word.word)

        try:
            while self.running:
                if not self._enabled:
                    await asyncio.sleep(0.5)
                    continue

                try:
                    # Wait for wake word
                    self.tray.set_status(TrayStatus.READY)
                    activated = await self._wait_for_wake_word()

                    if not activated or not self.running:
                        continue

                    # Process command
                    await self._process_command()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("main_loop_error", error=str(e))
                    self.tray.set_status(TrayStatus.ERROR)
                    await asyncio.sleep(1)

        finally:
            await self._shutdown()

    async def _wait_for_wake_word(self) -> bool:
        """Wait for wake word activation.

        Returns:
            True if wake word was detected.
        """
        logger.debug("waiting_for_wake_word")

        # If wake word detection is not available, wait for any audio
        if not self.wake_word.is_available:
            logger.warning("wake_word_not_available")
            # For testing without wake word, just wait
            await asyncio.sleep(2)
            return True

        return await self.wake_word.wait_for_activation(
            self.audio,
            timeout=None,  # Wait indefinitely
        )

    async def _process_command(self) -> None:
        """Process a voice command after wake word detection."""
        # Play acknowledgment beep
        if self.settings.audio.play_beep:
            await self.audio.play_beep(
                frequency=self.settings.audio.beep_frequency,
                duration=self.settings.audio.beep_duration,
            )

        # Listen and transcribe
        self.tray.set_status(TrayStatus.LISTENING)
        text = await self.stt.transcribe(timeout=self.settings.stt.timeout)

        if not text:
            await self._speak("I didn't catch that, Commander.")
            return

        logger.info("user_input", text=text)

        # Check for repeat/undo requests
        if self.context.is_repeat_request(text):
            await self._handle_repeat()
            return

        # Check for macro triggers first
        macro = await self.macros.find_by_trigger(text)
        if macro:
            await self._execute_macro(macro)
            return

        # Check for direct keybind match
        keybind = self.keybinds.find_by_alias(text)
        if keybind:
            await self._execute_keybind(keybind, text)
            return

        # Process through LLM
        self.tray.set_status(TrayStatus.PROCESSING)
        response = await self.llm.process(
            user_input=text,
            context=self.context.get_recent_history(),
            keybinds_context=self.keybinds.get_aliases_text(),
        )

        # Interpret and execute command
        command = self.interpreter.parse(response)
        await self._execute_command(command, text)

    async def _execute_command(self, command, user_input: str) -> None:
        """Execute a parsed command.

        Args:
            command: Parsed Command object.
            user_input: Original user input text.
        """
        # Handle different command types
        if command.type == CommandType.CREATE_MACRO:
            success, response = await self.macros.handle_create_command(
                name=command.macro_name,
                trigger=command.trigger_phrase,
                keys=command.macro_keys or [],
                action_type=command.macro_action_type or "press_key",
                duration=command.duration,
            )
            await self._speak(response)

        elif command.type == CommandType.DELETE_MACRO:
            success, response = await self.macros.handle_delete_command(
                name=command.macro_name
            )
            await self._speak(response)

        elif command.type == CommandType.LIST_MACROS:
            success, response = await self.macros.handle_list_command()
            await self._speak(response)

        elif command.is_keyboard_action:
            # Execute keyboard action
            success = await self.keyboard.execute_action(
                action=command.key_action,
                keys=command.keys,
                duration=command.duration if command.duration else None,
            )

            if success:
                await self._speak(command.response)
            else:
                await self._speak(
                    "I couldn't execute that command, Commander. "
                    "Make sure Star Citizen is in focus."
                )

        else:
            # Speak-only response
            await self._speak(command.response)

        # Update context
        self.context.add(user_input, command)

    async def _execute_macro(self, macro: dict) -> None:
        """Execute a macro.

        Args:
            macro: Macro dictionary.
        """
        logger.info("executing_macro", name=macro["name"])

        success = await self.macros.execute(macro)

        if success:
            response = macro.get("response", f"Macro {macro['name']} executed, Commander.")
            await self._speak(response)
        else:
            await self._speak("Macro execution failed, Commander.")

    async def _execute_keybind(self, keybind, user_input: str) -> None:
        """Execute a keybind directly.

        Args:
            keybind: Keybind object.
            user_input: Original user input.
        """
        logger.info("executing_keybind", name=keybind.name)

        success = await self.keyboard.execute_action(
            action=keybind.action,
            keys=keybind.keys,
            duration=keybind.duration if keybind.duration else None,
        )

        if success:
            await self._speak(keybind.response)
        else:
            await self._speak(
                "I couldn't execute that command, Commander. "
                "Is Star Citizen in focus?"
            )

    async def _handle_repeat(self) -> None:
        """Handle a repeat/again request."""
        last_cmd = self.context.get_last_keyboard_command()

        if last_cmd:
            logger.info("repeating_command", type=last_cmd.type.value)
            success = await self.keyboard.execute_action(
                action=last_cmd.key_action,
                keys=last_cmd.keys,
                duration=last_cmd.duration,
            )
            if success:
                await self._speak("Repeating last command, Commander.")
            else:
                await self._speak("Couldn't repeat, Commander.")
        else:
            await self._speak("No previous command to repeat, Commander.")

    async def _speak(self, text: str) -> None:
        """Synthesize and play speech.

        Args:
            text: Text to speak.
        """
        if not text:
            return

        self.tray.set_status(TrayStatus.SPEAKING)
        logger.info("speaking", text=text[:50])

        try:
            audio = await self.tts.synthesize(text)
            if audio is not None:
                await self.audio.play_audio(
                    audio,
                    sample_rate=self.settings.tts.sample_rate,
                )
            else:
                # TTS not available, just log
                logger.warning("tts_unavailable", text=text)
        except Exception as e:
            logger.error("speak_error", error=str(e))

    def _on_quit(self) -> None:
        """Handle quit request from tray."""
        logger.info("quit_requested")
        self.running = False

    def _on_toggle(self) -> None:
        """Handle toggle request from tray."""
        self._enabled = not self._enabled
        logger.info("toggled", enabled=self._enabled)

    def _on_show_macros(self) -> None:
        """Handle show macros request from tray."""
        # In a full implementation, this would show a GUI window
        logger.info("show_macros_requested")

    async def _shutdown(self) -> None:
        """Clean shutdown of all components."""
        logger.info("roland_shutting_down")

        # Cleanup
        self.keyboard.release_all_held_keys()
        self.audio.cleanup()
        self.stt.shutdown()
        self.tts.shutdown()
        await self.llm.close()
        self.tray.stop()

        logger.info("roland_shutdown_complete")


def handle_signals(roland: Roland) -> None:
    """Setup signal handlers for graceful shutdown.

    Args:
        roland: Roland instance.
    """

    def signal_handler(sig, frame):
        logger.info("signal_received", signal=sig)
        roland.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Roland - Star Citizen Voice Copilot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  roland                    Start with default config
  roland -c config.yaml     Start with custom config
  roland --version          Show version

Say "Roland" followed by your command to control Star Citizen.
        """,
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        help="Path to configuration file",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"Roland {__version__}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logger(level=log_level)

    # Print banner
    print(f"""
    ╔═══════════════════════════════════════════════╗
    ║                                               ║
    ║   ROLAND v{__version__:<10}                       ║
    ║   Star Citizen Voice Copilot                  ║
    ║                                               ║
    ║   Say "Roland" to activate                    ║
    ║   Press Ctrl+C to quit                        ║
    ║                                               ║
    ╚═══════════════════════════════════════════════╝
    """)

    # Create and run Roland
    roland = Roland(config_path=args.config)
    handle_signals(roland)

    try:
        asyncio.run(roland.run())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error("fatal_error", error=str(e))
        sys.exit(1)

    print("Roland offline. Fly safe, Commander.")


if __name__ == "__main__":
    main()
