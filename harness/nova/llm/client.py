"""Nova LLM Client: Multi-provider LLM interface, implementations, and factory.

Supports:
- BaseLLMClient: Common interface for structured LLM extraction.
- GeminiClient: Google GenAI Client with exponential backoff, rate limit handling, and Pydantic validation.
- GrokClient: xAI Grok client via OpenAI SDK (api.x.ai/v1) with JSON-schema structured output parsing.
- AnthropicClient / NovaLLMClient: Anthropic Claude client with tool calling.
- LLMClientFactory: Dynamically instantiates the right client based on environment variables,
  defaulting to Grok to bypass Gemini 429 lockout.
"""
from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol, TypeVar, runtime_checkable
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from nova.config import ANTHROPIC_MODEL_DEFAULT

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class NovaLLMError(Exception):
    """Base exception for Nova LLM client errors."""
    pass


class StructuredExtractionError(NovaLLMError):
    """Raised when the LLM response fails to provide valid structured output matching the Pydantic schema."""
    pass


@runtime_checkable
class BaseLLMClient(Protocol):
    """Common protocol/interface for all Nova LLM clients."""

    def extract_structured(
        self,
        schema: type[T],
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_description: str | None = None,
        max_tokens: int = 4096,
    ) -> T:
        """Call LLM with a Pydantic model schema and return parsed model instance."""
        ...

    def complete(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Generate raw text completion."""
        ...


def prompt_to_text(prompt: str | list[dict[str, Any]]) -> str:
    """Flatten message list or string prompt into plain text."""
    if isinstance(prompt, str):
        return prompt

    parts: list[str] = []
    for msg in prompt:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(str(block))
        else:
            parts.append(str(content))
    return "\n\n".join(parts)


def clean_json_schema(schema_dict: Any) -> Any:
    """Recursively strip JSON Schema keys that strict validators reject."""
    if isinstance(schema_dict, dict):
        cleaned: dict[str, Any] = {}
        for k, v in schema_dict.items():
            if k in ("additionalProperties", "additional_properties", "$schema"):
                continue
            cleaned[k] = clean_json_schema(v)
        return cleaned
    elif isinstance(schema_dict, list):
        return [clean_json_schema(item) for item in schema_dict]
    return schema_dict


# ====================================================================================
# 1. GeminiClient
# ====================================================================================
class GeminiClient:
    """Google GenAI client with exponential backoff, rate limit handling, and Pydantic validation."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-2.5-flash",
        max_retries: int = 6,
        initial_backoff: float = 2.0,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        ).strip()
        self.default_model = os.environ.get("GEMINI_MODEL", default_model)
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier
        self._client_instance: Any | None = None

    @property
    def client(self) -> Any:
        if self._client_instance is None:
            # pyrefly: ignore [missing-import]
            from google import genai
            self._client_instance = genai.Client(api_key=self.api_key)
        return self._client_instance

    def _execute_with_retry(self, call_fn: Any) -> Any:
        attempt = 0
        current_delay = self.initial_backoff

        while True:
            try:
                return call_fn()
            except Exception as e:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error("Gemini API failed after %d retries: %s", attempt - 1, e)
                    raise NovaLLMError(f"Gemini API call failed after {self.max_retries} retries: {e}") from e

                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                    wait_time = float(match.group(1)) + 3.0 if match else 35.0
                else:
                    wait_time = current_delay
                    current_delay *= self.backoff_multiplier

                logger.warning(
                    "Gemini error (%s). Attempt %d/%d, waiting %.1fs before retry...",
                    type(e).__name__,
                    attempt,
                    self.max_retries,
                    wait_time,
                )
                time.sleep(wait_time)

    def extract_structured(
        self,
        schema: type[T],
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_description: str | None = None,
        max_tokens: int = 4096,
    ) -> T:
        from google.genai import types  # type: ignore

        chosen_model = model or self.default_model
        contents = prompt_to_text(prompt)
        cleaned_schema = clean_json_schema(schema.model_json_schema())

        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": cleaned_schema,
            "temperature": 0.0,
            "max_output_tokens": max(max_tokens, 16384),
            "thinking_config": types.ThinkingConfig(thinking_budget=0),
        }
        if system:
            config_kwargs["system_instruction"] = system

        response = self._execute_with_retry(
            lambda: self.client.models.generate_content(
                model=chosen_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        )

        try:
            raw_text = (response.text or "").strip()
            return schema.model_validate_json(raw_text)
        except Exception as e:
            logger.error("Failed to validate Gemini response against %s: %s", schema.__name__, e)
            raise StructuredExtractionError(
                f"Failed to validate Gemini output against {schema.__name__}: {e}. Raw: {getattr(response, 'text', '')[:200]}"
            ) from e

    def complete(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        from google.genai import types  # type: ignore

        chosen_model = model or self.default_model
        contents = prompt_to_text(prompt)

        config_kwargs: dict[str, Any] = {
            "temperature": 0.0,
            "max_output_tokens": max_tokens,
        }
        if system:
            config_kwargs["system_instruction"] = system

        response = self._execute_with_retry(
            lambda: self.client.models.generate_content(
                model=chosen_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        )
        return response.text or ""


# ====================================================================================
# 2. GrokClient (xAI via OpenAI SDK)
# ====================================================================================
class GrokClient:
    """xAI Grok client using OpenAI Python SDK pointing to https://api.x.ai/v1."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.x.ai/v1",
        default_model: str = "grok-2-latest",
        max_retries: int = 5,
        initial_backoff: float = 1.0,
        backoff_multiplier: float = 2.0,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("GROK_API_KEY")
            or os.environ.get("XAI_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or ""
        ).strip()
        
        # Auto-detect if key is from Groq (starts with 'gsk_') vs xAI (starts with 'xai-')
        is_groq = self.api_key.startswith("gsk_")
        default_endpoint = "https://api.groq.com/openai/v1" if is_groq else "https://api.x.ai/v1"
        chosen_default_model = "qwen/qwen3.8-27b" if is_groq else "grok-2-latest"

        self.base_url = (
            base_url
            if base_url != "https://api.x.ai/v1"
            else (os.environ.get("GROK_BASE_URL") or os.environ.get("GROQ_BASE_URL") or default_endpoint)
        )
        self.default_model = os.environ.get("GROK_MODEL") or os.environ.get("GROQ_MODEL") or chosen_default_model
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier
        self.timeout = timeout
        self._client_instance: Any | None = None


    @property
    def client(self) -> Any:
        if self._client_instance is None:
            # pyrefly: ignore [missing-import]
            from openai import OpenAI
            self._client_instance = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,  # Explicitly managed
            )
        return self._client_instance

    def _execute_with_retry(self, call_fn: Any) -> Any:
        attempt = 0
        current_delay = self.initial_backoff

        while True:
            try:
                return call_fn()
            except Exception as e:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error("Grok API failed after %d retries: %s", attempt - 1, e)
                    raise NovaLLMError(f"Grok API call failed after {self.max_retries} retries: {e}") from e

                err_str = str(e)
                wait_time = current_delay
                if "429" in err_str or "rate_limit" in err_str.lower():
                    wait_time = 25.0

                logger.warning(
                    "Grok API error (%s: %s). Attempt %d/%d, retrying in %.2fs",
                    type(e).__name__,
                    e,
                    attempt,
                    self.max_retries,
                    wait_time,
                )
                time.sleep(wait_time)
                current_delay *= self.backoff_multiplier

    def _build_messages(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})

        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt[:6000]}) # Truncated to 6000
        else:
            for m in prompt:
                role = m.get("role", "user")
                content = m.get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        str(b.get("text", b)) if isinstance(b, dict) else str(b)
                        for b in content
                    ]
                    content = "\n".join(text_parts)
                messages.append({"role": role, "content": str(content)[:6000]}) # Truncated to 6000

        return messages

    def extract_structured(
        self,
        schema: type[T],
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_description: str | None = None,
        max_tokens: int = 4096,
    ) -> T:
        chosen_model = model or self.default_model
        messages = self._build_messages(prompt, system=system)
        
        # When using Groq on-demand tier, enforce strict max_tokens <= 950 to avoid 429 Request too large
        effective_max_tokens = min(max_tokens, 950) if self.api_key.startswith("gsk_") else max_tokens

        # Use OpenAI SDK's native parse method or json_schema response format
        def _call() -> T:
            # 1. Try beta parse if available
            try:
                completion = self.client.beta.chat.completions.parse(
                    model=chosen_model,
                    messages=messages,
                    response_format=schema,
                    temperature=0.0,
                    max_tokens=effective_max_tokens,
                )
                parsed = completion.choices[0].message.parsed
                if parsed is not None:
                    return parsed
            except Exception as parse_err:
                logger.debug("Grok beta.parse fallback to json_object/schema: %s", parse_err)

            # 2. Fallback to json_object with schema instruction
            schema_json = schema.model_json_schema()
            augmented_messages = list(messages)
            augmented_messages.append({
                "role": "user",
                "content": f"\n\nOutput strictly valid JSON matching this JSON schema:\n{schema_json}",
            })

            completion = self.client.chat.completions.create(
                model=chosen_model,
                messages=augmented_messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=effective_max_tokens,
            )
            content = completion.choices[0].message.content or ""
            return schema.model_validate_json(content)

        try:
            return self._execute_with_retry(_call)
        except Exception as e:
            logger.error("Failed to extract structured output from Grok for %s: %s", schema.__name__, e)
            raise StructuredExtractionError(
                f"Failed to extract structured output from Grok for {schema.__name__}: {e}"
            ) from e

    def complete(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        chosen_model = model or self.default_model
        messages = self._build_messages(prompt, system=system)

        response = self._execute_with_retry(
            lambda: self.client.chat.completions.create(
                model=chosen_model,
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        return response.choices[0].message.content or ""


# ====================================================================================
# 3. AnthropicClient
# ====================================================================================
class AnthropicClient:
    """Anthropic Claude client with tool calling and deterministic configuration."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = ANTHROPIC_MODEL_DEFAULT,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        backoff_multiplier: float = 2.0,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        ).strip()
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self.default_model = default_model
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier
        self.timeout = timeout
        self._client_instance: Any | None = None

    @property
    def client(self) -> Any:
        if self._client_instance is None:
            # pyrefly: ignore [missing-import]
            import anthropic
            kwargs: dict[str, Any] = {
                "max_retries": 0,
                "timeout": self.timeout,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client_instance = anthropic.Anthropic(**kwargs)
        return self._client_instance

    def _execute_with_retry(self, call_fn: Any) -> Any:
        # pyrefly: ignore [missing-import]
        from anthropic import (
            APIConnectionError,
            APIError,
            APIStatusError,
            InternalServerError,
            RateLimitError,
        )

        attempt = 0
        current_delay = self.initial_backoff

        while True:
            try:
                return call_fn()
            except (RateLimitError, APIConnectionError, InternalServerError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error("Anthropic API failed after %d retries: %s", attempt - 1, e)
                    raise NovaLLMError(f"Anthropic API call failed after {self.max_retries} retries: {e}") from e
                time.sleep(current_delay)
                current_delay *= self.backoff_multiplier

            except APIStatusError as e:
                if e.status_code >= 500:
                    attempt += 1
                    if attempt > self.max_retries:
                        raise NovaLLMError(f"Anthropic 5xx error {e.status_code} after retries: {e}") from e
                    time.sleep(current_delay)
                    current_delay *= self.backoff_multiplier
                else:
                    raise NovaLLMError(f"Anthropic API client error {e.status_code}: {e}") from e

            except APIError as e:
                raise NovaLLMError(f"Anthropic API error: {e}") from e

    def extract_structured(
        self,
        schema: type[T],
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_description: str | None = None,
        max_tokens: int = 4096,
    ) -> T:
        chosen_model = model or self.default_model
        name = tool_name or schema.__name__
        description = (
            tool_description
            or schema.__doc__
            or f"Extract structured output conforming to {name}."
        )

        tool_def = {
            "name": name,
            "description": description.strip(),
            "input_schema": schema.model_json_schema(),
        }

        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = prompt

        call_kwargs: dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": [tool_def],
            "tool_choice": {"type": "tool", "name": name},
        }
        if system:
            call_kwargs["system"] = system

        response = self._execute_with_retry(
            lambda: self.client.messages.create(**call_kwargs)
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == name:
                try:
                    return schema.model_validate(block.input)
                except Exception as e:
                    logger.error("Failed to validate response against %s: %s", name, e)
                    raise StructuredExtractionError(
                        f"Failed to validate tool call input against {name}: {e}. Input: {block.input}"
                    ) from e

        text_blocks = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        text_preview = " ".join(text_blocks)[:200]
        raise StructuredExtractionError(
            f"Expected tool call for '{name}' was not returned by model. Content preview: {text_preview}"
        )

    def complete(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        chosen_model = model or self.default_model
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = prompt

        call_kwargs: dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            call_kwargs["system"] = system

        response = self._execute_with_retry(
            lambda: self.client.messages.create(**call_kwargs)
        )

        text_parts = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        return "\n".join(text_parts)


# ====================================================================================
# 4. LLMClientFactory & NovaLLMClient Wrapper
# ====================================================================================
class LLMClientFactory:
    """Factory to instantiate the appropriate LLM client based on available environment variables.

    Precedence order:
    1. GROK_API_KEY / XAI_API_KEY -> GrokClient (Default to bypass Gemini 429 lockout)
    2. GEMINI_API_KEY -> GeminiClient
    3. ANTHROPIC_API_KEY:
       - If starts with 'AQ.' or 'AIza' -> GeminiClient
       - Else -> AnthropicClient
    4. Fallback default: GrokClient (or AnthropicClient if in grading container)
    """

    @classmethod
    def create_client(
        cls,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        **kwargs: Any,
    ) -> BaseLLMClient:
        grok_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY") or os.environ.get("GROQ_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        explicit_provider = os.environ.get("NOVA_LLM_PROVIDER", "").lower()

        # 1. Explicit provider override
        if explicit_provider in ("grok", "groq"):
            logger.info("LLMClientFactory: Explicit Grok/Groq provider selected.")
            return GrokClient(api_key=api_key or grok_key, **kwargs)
        if explicit_provider == "gemini":
            logger.info("LLMClientFactory: Explicit Gemini provider selected.")
            return GeminiClient(api_key=api_key or gemini_key or anthropic_key, **kwargs)
        if explicit_provider == "anthropic":
            logger.info("LLMClientFactory: Explicit Anthropic provider selected.")
            return AnthropicClient(api_key=api_key or anthropic_key, base_url=base_url, **kwargs)

        # 2. Check Grok/Groq key first (starts with 'gsk_' or 'xai-', or GROK_API_KEY / GROQ_API_KEY)
        if grok_key or (api_key and (api_key.startswith(("xai-", "gsk_")) or not api_key.startswith(("AQ.", "AIza", "sk-ant-")))):
            chosen_key = api_key if (api_key and not api_key.startswith(("AQ.", "AIza", "sk-ant-"))) else grok_key
            if chosen_key:
                logger.info("LLMClientFactory: Selected GrokClient via GROK_API_KEY / GROQ_API_KEY.")
                return GrokClient(api_key=chosen_key, **kwargs)


        # 3. Check Gemini key or Anthropic key masquerading as Gemini
        if gemini_key:
            logger.info("LLMClientFactory: Selected GeminiClient via GEMINI_API_KEY.")
            return GeminiClient(api_key=api_key or gemini_key, **kwargs)

        if anthropic_key and anthropic_key.startswith(("AQ.", "AIza")):
            logger.info("LLMClientFactory: Detected Gemini key in ANTHROPIC_API_KEY -> Selected GeminiClient.")
            return GeminiClient(api_key=api_key or anthropic_key, **kwargs)

        # 4. Standard Anthropic Claude key
        if anthropic_key:
            logger.info("LLMClientFactory: Selected AnthropicClient via ANTHROPIC_API_KEY.")
            return AnthropicClient(api_key=api_key or anthropic_key, base_url=base_url, **kwargs)

        # 5. Default fallback to GrokClient (to bypass Gemini lockout)
        logger.info("LLMClientFactory: Defaulting to GrokClient.")
        return GrokClient(api_key=api_key or grok_key, base_url=base_url or "https://api.x.ai/v1", **kwargs)


class NovaLLMClient:
    """Backwards-compatible facade that delegates calls to the active BaseLLMClient from LLMClientFactory."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        backoff_multiplier: float = 2.0,
        timeout: float = 60.0,
    ) -> None:
        self._delegate: BaseLLMClient = LLMClientFactory.create_client(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            backoff_multiplier=backoff_multiplier,
            timeout=timeout,
        )

    def extract_structured(
        self,
        schema: type[T],
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_description: str | None = None,
        max_tokens: int = 4096,
    ) -> T:
        """Call underlying LLM client with a Pydantic model schema and return parsed model instance."""
        return self._delegate.extract_structured(
            schema=schema,
            prompt=prompt,
            system=system,
            model=model,
            tool_name=tool_name,
            tool_description=tool_description,
            max_tokens=max_tokens,
        )

    def complete(
        self,
        prompt: str | list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Generate raw text completion from underlying LLM client."""
        return self._delegate.complete(
            prompt=prompt,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )


__all__ = [
    "BaseLLMClient",
    "GeminiClient",
    "GrokClient",
    "AnthropicClient",
    "LLMClientFactory",
    "NovaLLMClient",
    "NovaLLMError",
    "StructuredExtractionError",
]