# Roland

**Star Citizen Voice Copilot** - A JARVIS-style AI assistant for Star Citizen

Roland is a voice-controlled copilot that responds to natural language commands, executes keyboard macros, and speaks with a custom AI voice. Built for immersion and hands-free ship control.

## Features

- **Wake Word Activation** - Say "Roland" to activate the assistant
- **Natural Language Commands** - "Lower the landing gear", "Engage quantum drive", etc.
- **Dynamic Macros** - Create macros on-the-fly: "Roland, when I say panic mode, press C"
- **Custom Voice** - JARVIS-style voice using your own audio sample
- **Local Processing** - All AI processing runs locally (Ollama) for privacy
- **Star Citizen Optimized** - Pre-configured keybinds for common ship controls

## Quick Start

### Prerequisites

- Python 3.10, 3.11, or 3.12
- [Ollama](https://ollama.ai/) installed and running
- **Windows 10/11** or **Linux** (Ubuntu/Debian recommended)
- A microphone
- GPU recommended for faster TTS/STT (but not required)

### Installation (Windows)

```powershell
# Clone the repository
git clone https://github.com/YourBr0ther/roland.git
cd roland

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install Python dependencies (this will take a few minutes - downloads ~2GB of ML models)
pip install -e .

# Pull the LLM model
ollama pull llama3.2

# Start Ollama server (in a separate terminal)
ollama serve
```

### Installation (Linux)

```bash
# Clone the repository
git clone https://github.com/YourBr0ther/roland.git
cd roland

# Install system dependencies (Ubuntu/Debian) - REQUIRED
sudo apt-get install portaudio19-dev python3-pyaudio gir1.2-appindicator3-0.1 xdotool

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install Python dependencies (this will take a few minutes - downloads ~2GB of ML models)
pip install -e .

# Pull the LLM model
ollama pull llama3.2

# Start Ollama server (in a separate terminal or background)
ollama serve
```

> **Note**: The first run will download additional models for TTS (~2GB) and STT (~500MB). Make sure you have sufficient disk space.

### Configuration

1. Copy the default config:
```bash
cp config/default_config.yaml config/config.yaml
```

2. Add your voice sample for cloning (6-10 seconds of clear speech):
```bash
cp /path/to/your/voice.wav data/voices/reference.wav
```

3. Edit `config/config.yaml` to customize settings

### Running

```bash
# Start Roland
roland

# Or with debug logging
roland --debug

# Or with custom config
roland -c /path/to/config.yaml
```

## Usage

### Basic Commands

| Say This | Roland Does |
|----------|-------------|
| "Roland, lower the landing gear" | Presses N |
| "Roland, engage quantum drive" | Holds B for quantum spool |
| "Roland, request landing permission" | Presses Ctrl+N |
| "Roland, power to weapons" | Presses F5 |
| "Roland, flight ready" | Presses R |

### Creating Macros

```
"Roland, when I say panic mode, press C"
"Roland, create a macro: if I say boost, hold shift"
```

### Managing Macros

```
"Roland, list my macros"
"Roland, delete the panic mode macro"
```

### Contextual Commands

```
"Roland, do that again"      # Repeats last action
"Roland, repeat"             # Same as above
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ROLAND COPILOT                          │
├─────────────────────────────────────────────────────────────────┤
│  Microphone → Wake Word (OpenWakeWord) → STT (Whisper)          │
│                              ↓                                   │
│  Keyboard (pynput) ← Command Interpreter ← LLM (Ollama)         │
│                              ↓                                   │
│  Macro Storage (SQLite) ↔ Context Manager                       │
│                              ↓                                   │
│  Speaker ← TTS (Coqui XTTS) ← Response Generator                │
│                                                                  │
│  [System Tray: Status, Settings, Exit]                          │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
roland/
├── roland/
│   ├── main.py              # Application entry point
│   ├── config.py            # Configuration management
│   ├── audio/               # Audio I/O, STT, TTS, wake word
│   ├── llm/                 # Ollama client, command interpretation
│   ├── keyboard/            # Keyboard control, keybinds
│   ├── macros/              # Macro management and storage
│   ├── ui/                  # System tray interface
│   └── utils/               # Logging utilities
├── config/
│   ├── default_config.yaml  # Default configuration
│   ├── keybinds.yaml        # Star Citizen keybind definitions
│   └── responses.yaml       # Response templates
├── data/
│   ├── voices/              # Voice samples for TTS cloning
│   └── macros.db            # Macro database
└── tests/                   # Unit tests
```

## Configuration

### Key Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `wake_word.word` | Wake word to activate | "roland" |
| `llm.model` | Ollama model | "llama3.2" |
| `stt.model` | Whisper model size | "base.en" |
| `keyboard.require_game_focus` | Only send keys when SC focused | true |

### Environment Variables

Settings can be overridden with environment variables prefixed with `ROLAND_`:

```bash
export ROLAND_LLM__MODEL=mistral
export ROLAND_STT__MODEL=small.en
```

## Keybinds

Default Star Citizen keybinds are defined in `config/keybinds.yaml`. You can customize these to match your in-game bindings.

### Adding Custom Keybinds

```yaml
# config/keybinds.yaml
custom:
  my_action:
    keys: ["ctrl", "shift", "f1"]
    action: "combo"
    aliases: ["my special action", "do the thing"]
    response: "Custom action executed, Commander."
```

## Voice Sample Requirements

For the best voice cloning results:

- **Duration**: 6-10 seconds of speech
- **Quality**: Clear audio, minimal background noise
- **Format**: WAV (16-bit, 22050Hz or higher)
- **Content**: Natural speech in the tone you want Roland to use

## Troubleshooting

### "Wake word not detected"

- Ensure your microphone is working
  - **Windows:** Check Settings → Sound → Input
  - **Linux:** Run `arecord -l`
- Check audio input device in config
- Try adjusting `wake_word.threshold` (lower = more sensitive)

### "Ollama not available"

- Ensure Ollama is running: `ollama serve`
- Check if model is installed: `ollama list`
- Verify base_url in config matches Ollama's address

### "Keys not being sent to Star Citizen"

**Windows:**
- Make sure Star Citizen window is focused
- Run as Administrator if keyboard input isn't working
- Try running with `keyboard.require_game_focus: false` for testing

**Linux:**
- Make sure Star Citizen window is focused
- Add your user to the `input` group: `sudo usermod -aG input $USER`
- Try running with `keyboard.require_game_focus: false` for testing

### "TTS not working"

- First run downloads the XTTS model (~2GB)
- Ensure voice sample exists at the configured path
- Check GPU availability for faster synthesis

### "ImportError: this platform is not supported" (pynput) - Linux only

- pynput requires an X display to function on Linux
- Make sure you're running in a graphical environment, not SSH
- If testing headless, keyboard features will be disabled gracefully
- **Windows users**: This error should not occur on Windows

### "No module named 'pyaudio'" or "PortAudio library not found"

**Windows:**
- Install PyAudio via pip: `pip install PyAudio`
- If that fails, download the wheel from [unofficial binaries](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio)

**Linux:**
- Install system dependencies first:
  ```bash
  sudo apt-get install portaudio19-dev python3-pyaudio
  ```
- Then reinstall PyAudio: `pip install PyAudio`

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Style

```bash
black roland/
ruff check roland/
```

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

MIT License - See LICENSE file for details.

## Acknowledgments

- [Coqui TTS](https://github.com/idiap/coqui-ai-TTS) - Voice synthesis (community fork with Python 3.12 support)
- [OpenWakeWord](https://github.com/dscripka/openWakeWord) - Wake word detection
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) - Speech-to-text
- [Ollama](https://ollama.ai/) - Local LLM inference
- [pynput](https://github.com/moses-palmer/pynput) - Keyboard control

## Tech Stack

| Component | Library | Purpose |
|-----------|---------|---------|
| Wake Word | OpenWakeWord | Detect "Roland" activation |
| Speech-to-Text | Faster-Whisper | Transcribe voice commands |
| LLM | Ollama (llama3.2) | Interpret natural language |
| Text-to-Speech | Coqui XTTS | Clone voice for responses |
| Keyboard | pynput | Send keypresses to game |
| Storage | SQLite | Store custom macros |
| Config | Pydantic | Type-safe configuration |

---

*"At your service, Commander."* - Roland
