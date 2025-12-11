"""Ollama LLM client for Roland.

Provides async interface to local Ollama instance for
natural language command interpretation.
"""

import asyncio
import json
from typing import AsyncIterator, Optional

import httpx

from roland.config import get_settings
from roland.llm.prompts import get_system_prompt, get_context_prompt
from roland.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Async client for Ollama LLM API.

    Communicates with a local Ollama instance to process
    voice commands and generate responses.

    Attributes:
        model: Ollama model name.
        base_url: Ollama API base URL.
        temperature: Sampling temperature.
        max_tokens: Maximum response tokens.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        max_tokens: int = 500,
        timeout: int = 30,
    ):
        """Initialize the Ollama client.

        Args:
            model: Ollama model name (e.g., llama3.2, mistral).
            base_url: Ollama API base URL.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens in response.
            timeout: Request timeout in seconds.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._system_prompt = get_system_prompt()

    @classmethod
    def from_config(cls) -> "OllamaClient":
        """Create OllamaClient from app configuration.

        Returns:
            Configured OllamaClient instance.
        """
        settings = get_settings()
        return cls(
            model=settings.llm.model,
            base_url=settings.llm.base_url,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            timeout=settings.llm.timeout,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Returns:
            Async HTTP client.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def is_available(self) -> bool:
        """Check if Ollama is running and model is available.

        Returns:
            True if Ollama is accessible.
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our model is available (with or without :latest)
                model_base = self.model.split(":")[0]
                available = any(model_base in m for m in models)
                if not available:
                    logger.warning(
                        "ollama_model_not_found",
                        model=self.model,
                        available_models=models,
                    )
                return True  # Ollama is running
            return False
        except Exception as e:
            logger.error("ollama_not_available", error=str(e))
            return False

    async def process(
        self,
        user_input: str,
        context: Optional[list[dict]] = None,
        keybinds_context: str = "",
    ) -> dict:
        """Process user input and return structured command.

        Args:
            user_input: User's voice command text.
            context: Optional conversation history.
            keybinds_context: Optional additional keybind info.

        Returns:
            Parsed command dictionary.
        """
        # Build system prompt with context
        system_prompt = get_system_prompt(keybinds_context)
        if context:
            system_prompt += get_context_prompt(context)

        # Make request
        try:
            response_text = await self._generate(user_input, system_prompt)

            # Parse JSON response
            command = self._parse_response(response_text)

            logger.info(
                "llm_command_generated",
                user_input=user_input[:50],
                action=command.get("action"),
            )

            return command

        except Exception as e:
            logger.error("llm_process_error", error=str(e), user_input=user_input[:50])
            return {
                "action": "speak_only",
                "response": "I'm having trouble processing that request, Commander. Could you try again?",
            }

    async def _generate(self, prompt: str, system_prompt: str) -> str:
        """Generate response from Ollama.

        Args:
            prompt: User prompt.
            system_prompt: System prompt.

        Returns:
            Generated text response.
        """
        client = await self._get_client()

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        logger.debug("ollama_request", model=self.model, prompt_length=len(prompt))

        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

        data = response.json()
        return data.get("response", "")

    async def stream(
        self,
        user_input: str,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens from Ollama.

        Args:
            user_input: User's input text.
            system_prompt: Optional system prompt override.

        Yields:
            Response tokens as they're generated.
        """
        client = await self._get_client()

        payload = {
            "model": self.model,
            "prompt": user_input,
            "system": system_prompt or self._system_prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        async with client.stream("POST", "/api/generate", json=payload) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if token := data.get("response"):
                            yield token
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    def _parse_response(self, response_text: str) -> dict:
        """Parse LLM response into command dictionary.

        Handles various response formats and extracts JSON.

        Args:
            response_text: Raw LLM response text.

        Returns:
            Parsed command dictionary.
        """
        # Clean up response
        text = response_text.strip()

        # Try to find JSON in response
        # First, try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass

        # Try to extract JSON from { to }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # If all parsing fails, return speak_only with the text
        logger.warning("llm_json_parse_failed", response=text[:100])
        return {
            "action": "speak_only",
            "response": "I understand, Commander, but I'm not sure how to execute that command.",
        }

    def update_system_prompt(self, keybinds_context: str = "") -> None:
        """Update the system prompt with new keybinds.

        Args:
            keybinds_context: Additional keybind information.
        """
        self._system_prompt = get_system_prompt(keybinds_context)
        logger.info("system_prompt_updated")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("ollama_client_closed")

    def get_status(self) -> dict:
        """Get client status information.

        Returns:
            Dictionary with status information.
        """
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
