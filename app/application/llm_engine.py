# ─────────────────────────────────────────────────────
# Module   : app/application/llm_engine.py
# Layer    : Application
# Pillar   : P3 (Concurrency), P4 (Performance), P6 (Resilience), P8 (Code Quality)
# Complexity: O(1) time, O(1) space (Network bound)
# ─────────────────────────────────────────────────────

import json
import base64
import random
import asyncio
from typing import Any, Dict, Tuple, Optional
import structlog
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.exceptions import ProviderNotAvailableError, ExternalServiceError

logger = structlog.get_logger("app")

# Resilience Constants
MAX_RETRIES = 3
BACKOFF_BASE = 4.0  
MAX_DELAY = 60.0    


class LLMEngine:
    """
    Handles provider routing, native async I/O, advanced rate-limit resilience, 
    and self-healing JSON schema enforcement.
    """
    def __init__(self, provider: str, model: str):
        self.provider = provider.lower()
        self.model = model
        self._gemini_client = None
        
        # OPTIMIZATION: Create client once at initialization
        if self.provider == "gemini" and settings.GOOGLE_GEMINI_API_KEY:
            self._gemini_client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    async def _wait_with_backoff(self, attempt: int) -> None:
        """Calculates exponential backoff time with random jitter."""
        delay = min(MAX_DELAY, (BACKOFF_BASE ** attempt)) + random.uniform(0, 1)
        logger.warning(f"Rate limit hit. Retrying in {delay:.2f}s... (Attempt {attempt+1}/{MAX_RETRIES})")
        await asyncio.sleep(delay)

    def _is_rate_limit(self, e: Exception) -> bool:
        """
        Broadly detects 429 Rate Limit and Quota Exhaustion errors 
        across multiple SDK exception types and strings.
        """
        error_str = str(e).lower()
        return any(phrase in error_str for phrase in [
            "429", 
            "too many requests", 
            "quota", 
            "resourceexhausted", 
            "resource exhausted"
        ])

    async def extract(self, image_bytes: bytes, mime_type: str, prompt: str) -> Tuple[Dict[str, Any], dict]:
        """
        Executes the extraction request with multi-stage resilience.
        Includes a self-healing LLM-based JSON repair fallback if decoding fails.
        """
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        # Stage 1: Initial Extraction Attempt
        try:
            raw_response, usage_dict = await self._execute_with_retries(prompt, b64_image, mime_type)
            cleaned = self._clean_json_string(raw_response)
            return json.loads(cleaned), usage_dict

        except json.JSONDecodeError as e:
            logger.warning("LLMEngine: JSON Decode Error on initial pass. Attempting self-healing repair...", error=str(e))
            
            # Stage 2: Self-Healing JSON Repair
            # Uses a text-only prompt to save tokens (P4 Performance)
            try:
                repair_prompt = (
                    f"The previous output was invalid JSON. Fix this string and return strictly valid JSON:\n\n"
                    f"{raw_response[:2000]}..." # Truncate to avoid exploding context windows
                )
                
                repair_response, repair_usage = await self._execute_with_retries(repair_prompt, None, None)
                cleaned_repair = self._clean_json_string(repair_response)
                
                # Combine token usage from both the failed run and the repair run
                combined_usage = {
                    "prompt_tokens": usage_dict.get("prompt_tokens", 0) + repair_usage.get("prompt_tokens", 0),
                    "completion_tokens": usage_dict.get("completion_tokens", 0) + repair_usage.get("completion_tokens", 0),
                    "total_tokens": usage_dict.get("total_tokens", 0) + repair_usage.get("total_tokens", 0)
                }
                
                return json.loads(cleaned_repair), combined_usage
                
            except Exception as repair_e:
                logger.error("LLMEngine: JSON self-healing failed.", error=str(repair_e))
                raise ExternalServiceError("Failed to extract valid JSON even after repair attempt.")
                
    def _clean_json_string(self, raw_str: str) -> str:
        """Safely strips markdown formatting that LLMs often incorrectly append."""
        return raw_str.replace("```json", "").replace("```", "").strip()

    async def _execute_with_retries(self, prompt: str, b64_image: Optional[str] = None, mime_type: Optional[str] = None) -> Tuple[str, dict]:
        """
        Wraps the provider execution loop with robust 429 rate limit resilience.
        """
        for attempt in range(MAX_RETRIES):
            try:
                return await self._route_provider(prompt, b64_image, mime_type)
                
            except Exception as e:
                if self._is_rate_limit(e):
                    if attempt < MAX_RETRIES - 1:
                        await self._wait_with_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max rate limit retries exceeded for {self.provider}", error=str(e))
                        raise ExternalServiceError(f"Provider {self.provider} quota/rate limits exhausted.")
                else:
                    # Non-retryable error (e.g., Auth failure, Bad Request)
                    logger.error(f"LLM Error (Non-Retryable): {e}")
                    raise ExternalServiceError(f"Provider {self.provider} failed: {str(e)}")
                    
        raise ExternalServiceError("Execution failed unexpectedly.")

    async def _route_provider(self, prompt: str, b64_image: Optional[str], mime_type: Optional[str]) -> Tuple[str, dict]:
        """Routes the request natively using async IO for performance."""
        match self.provider:
            case "gemini":
                if not self._gemini_client:
                    raise ProviderNotAvailableError("Gemini API key not configured.")
                return await self._call_gemini_async(prompt, b64_image, mime_type)
            
            case "openai":
                raise NotImplementedError("OpenAI provider implementation pending.")
            
            case "anthropic":
                raise NotImplementedError("Anthropic provider implementation pending.")
            
            case _:
                raise ProviderNotAvailableError(f"Unsupported provider: {self.provider}")

    async def _call_gemini_async(self, prompt: str, b64_image: Optional[str], mime_type: Optional[str]) -> Tuple[str, dict]:
        """
        Native Async wrapper for Google GenAI SDK (P3 Concurrency).
        Supports both Multimodal (Image+Text) and Text-Only (Repair) execution.
        """
        contents = [types.Part.from_text(text=prompt)]
        
        # Only attach image if provided (saves tokens on repair runs)
        if b64_image and mime_type:
            contents.append(types.Part.from_bytes(data=base64.b64decode(b64_image), mime_type=mime_type))
            
        # P4 Performance & P6 Resilience: Force JSON MIME type output
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0  # Zero temperature strictly enforces factual extraction
        )
            
        response = await self._gemini_client.aio.models.generate_content(
            model=self.model,
            config=config,
            contents=contents
        )
        
        # Safely extract token metrics
        meta = response.usage_metadata
        usage = {
            "prompt_tokens": meta.prompt_token_count if meta else 0,
            "completion_tokens": meta.candidates_token_count if meta else 0,
            "total_tokens": meta.total_token_count if meta else 0
        }
        
        return response.text, usage