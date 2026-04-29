# ─────────────────────────────────────────────────────
# Module   : app/application/orchestrator.py
# Layer    : Application
# Pillar   : P1 (Architecture), P3 (Concurrency), P7 (Observability)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

import asyncio
import structlog
import base64
import json
from typing import Any, Dict

from app.domain.entities import ExtractionJob, ExtractionResult
from app.domain.value_objects import ImageMetadata
from app.application.prompt_registry import get_prompt, requires_color
from app.core.exceptions import BaseAppException
from app.core.config import settings
from app.infrastructure.image_processor import optimize_image_for_llm
from app.core.http import get_client
from app.domain.api_schemas import BatchExtractionRequest, DocumentItem
from app.application.llm_engine import LLMEngine


# Import interface to Infrastructure (Ports & Adapters — P1)
from app.application import ports

logger = structlog.get_logger("app")

# Concurrency control for discord bot
discord_extraction_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_EXTRACTIONS)

async def process_discord_extraction(
    user_id: str,
    channel_id: str,
    message_id: str,
    image_bytes: bytes,
    mime_type: str,
    provider: str,
    model: str,
    doc_type_hint: str = "auto"
) -> ExtractionJob:
    """
    Primary use-case orchestration for Discord-initiated extractions.
    Ensures safe concurrency, domain mapping, logging context, and fire-and-forget persistence.
    
    Args:
        doc_type_hint: Document type hint from user command (e.g., 'receipt', 'passport', 'auto').
                       Controls prompt selection, image optimization, and schema enforcement.
    """
    # 1. Initialize Domain Entity (Computes SHA256, strictly discards raw bytes)
    meta = ImageMetadata.from_bytes(image_bytes, mime_type)
    
    job = ExtractionJob(
        discord_user_id=user_id,
        discord_channel_id=channel_id,
        discord_message_id=message_id,
        image_meta=meta,
        provider=provider,
        model=model
    )
    
    job.mark_processing()
    
    # ALWAYS emit extraction_id in every log line for that extraction (structlog bind).
    structlog.contextvars.bind_contextvars(extraction_id=str(job.job_id))
    
    # DATA: INTERNAL/CONFIDENTIAL rules met (logging hash and size only)
    logger.info("Starting extraction job", image_hash=meta.sha256_hash, size=meta.size_bytes, doc_type_hint=doc_type_hint)

    async with discord_extraction_semaphore:
        try:
            # 1.5. Optimize Image (P4 Performance)
            # Preserve color for documents that need it (passports, IDs)
            preserve_color = requires_color(doc_type_hint)
            optimized_bytes, optimized_mime = optimize_image_for_llm(image_bytes, preserve_color=preserve_color)
            
            # 2. Get document-type-specific prompt from registry
            prompt = get_prompt(doc_type_hint)
            
            # 3. Execute LLM Extraction
            engine = LLMEngine(provider=provider, model=model)
            raw_result, usage_dict = await engine.extract(optimized_bytes, optimized_mime, prompt)
            
            # 4. Clean schema and inject token usage
            cleaned_result = _clean_llm_output(raw_result)
            cleaned_result["token_usage"] = usage_dict
            
            result = ExtractionResult(**cleaned_result)
            job.mark_success(result)
            
            # P7: Log the tokens natively in structlog
            logger.info(
                "Extraction successful", 
                doc_type=result.document_type,
                confidence=result.overall_confidence,
                tokens=usage_dict["total_tokens"]
            )
            
            # 5. Persistence (ALWAYS fire-and-forget Sheets writes)
            asyncio.create_task(_persist_safely(job))
            
        except BaseAppException as e:
            logger.error("Domain/Application Error during extraction", error=e.message)
            job.mark_failed(e.message)
        except Exception as e:
            logger.exception("Unexpected system failure during extraction")
            job.mark_failed("An unexpected internal error occurred.")
            
    return job

async def _persist_safely(job: ExtractionJob) -> None:
    """Fire-and-forget wrapper to prevent persistence failures from crashing the bot response."""
    try:
        await ports.save_extraction_to_sheets(job)
        logger.info("Successfully persisted extraction to Sheets")
    except Exception as e:
        logger.error("Failed to persist extraction to Sheets. Data returned to user but not logged.", error=str(e))

# Independent semaphore for API batch processing to avoid colliding with Discord traffic
batch_extraction_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_EXTRACTIONS)

async def process_batch_documents(request: BatchExtractionRequest) -> Dict[str, Any]:
    """
    Processes a batch of documents concurrently using the provided LLM and HTTP client.
    Now supports entirely dynamic JSON schemas for the API tier.
    """
    
    # Pre-compute the prompt once for the entire batch
    if request.custom_schema:
        active_prompt = _build_dynamic_api_prompt(request.extract_type, request.custom_schema)
        is_dynamic_schema = True
    else:
        active_prompt = request.prompt or "Extract all data into structured JSON."
        is_dynamic_schema = False

    async def process_single_doc(doc: DocumentItem) -> Dict[str, Any]:
        async with batch_extraction_semaphore:
            try:
                # 1. Fetch File Bytes safely
                file_bytes = None
                if doc.base64_content:
                    file_bytes = base64.b64decode(doc.base64_content)
                elif doc.file_url:
                    client = get_client()
                    resp = await client.get(str(doc.file_url))
                    resp.raise_for_status()
                    file_bytes = resp.content
                else:
                    raise ValueError("Must provide either file_url or base64_content")

                # 2. Optimize Image
                opt_bytes, opt_mime = optimize_image_for_llm(file_bytes)
        

                # 3. LLM Extraction
                engine = LLMEngine(provider=request.provider, model=request.model)
                raw_result, usage_dict = await engine.extract(opt_bytes, opt_mime, active_prompt)

                # 4. Routing Validation Logic (P1 Architecture Trade-off)
                # TRADE-OFF: API users want raw custom schemas, while Discord users need 
                # strictly validated hierarchical models with confidence metrics. 
                # We branch here to satisfy both contracts.
                if is_dynamic_schema:
                    # Return exactly what the LLM generated (which matches the user's schema)
                    final_data = raw_result
                else:
                    # Apply legacy Discord wrapper for flat prompts
                    final_data = _clean_llm_output(raw_result)

                # 5. Resilience Padding
                await asyncio.sleep(1.0)
                
                logger.info("Batch extraction successful", doc_id=doc.id, tokens=usage_dict.get("total_tokens", 0))
                
                # Attach token metadata at the root level so it doesn't pollute the user's custom schema
                return {
                    "id": doc.id, 
                    "status": "success", 
                    "data": final_data,
                    "token_usage": usage_dict 
                }

            except Exception as e:
                logger.error("Batch extraction failed for document", doc_id=doc.id, error=str(e))
                return {"id": doc.id, "status": "error", "error": str(e)}

    # Fan-out execution
    tasks = [process_single_doc(doc) for doc in request.documents]
    results = await asyncio.gather(*tasks)

    return {"results": results}

def _build_dynamic_api_prompt(extract_type: str, custom_schema: Dict[str, Any]) -> str:
    """
    P8 Code Quality: Dynamically constructs the system prompt to force the LLM 
    to adhere strictly to the user-provided API schema.
    """
    return (
        f"You are an expert Data Extraction AI specializing in '{extract_type}' documents.\n"
        f"Extract the data from the provided image and format it EXACTLY according to the schema below.\n\n"
        f"MANDATORY RULES:\n"
        f"1. Output ONLY valid JSON. No markdown formatting, no conversational text.\n"
        f"2. Your JSON structure MUST perfectly match the requested schema.\n"
        f"3. If a requested field is not present or illegible in the document, return `null` for that field.\n"
        f"4. Do NOT invent or hallucinate data.\n\n"
        f"REQUESTED SCHEMA:\n"
        f"{json.dumps(custom_schema, indent=2)}"
    )

def _clean_llm_output(raw_data: dict) -> dict:
    """
    P6 Resilience: Normalizes raw LLM output into the generic ExtractionData schema.
    Handles both the new 'sections'/'tables' format and legacy 'header_info'/'line_items' format.
    """
    # ── 1. Migrate legacy formats ────────────────────────────────
    if "data" not in raw_data:
        raw_data["data"] = {}
    
    data_block = raw_data["data"]
    
    # Legacy format migration: 'fields' -> sections
    if "fields" in raw_data and "sections" not in data_block:
        data_block["sections"] = {"extracted_fields": raw_data.pop("fields")}
    
    # Legacy format migration: header_info/summary_totals -> sections, line_items -> tables
    if "header_info" in data_block or "summary_totals" in data_block or "line_items" in data_block:
        sections = {}
        if "header_info" in data_block:
            sections["header_info"] = data_block.pop("header_info")
        if "summary_totals" in data_block:
            sections["summary_totals"] = data_block.pop("summary_totals")
        # Merge with any existing sections
        if "sections" not in data_block:
            data_block["sections"] = {}
        data_block["sections"].update(sections)
        
        if "line_items" in data_block:
            data_block["tables"] = data_block.pop("line_items")
    
    # ── 2. Ensure required keys exist ────────────────────────────
    if "sections" not in data_block or not isinstance(data_block["sections"], dict):
        data_block["sections"] = {}
    
    if "tables" not in data_block or not isinstance(data_block["tables"], list):
        data_block["tables"] = []
    
    # ── 3. Wrap naked values into ExtractedField structure ───────
    def _wrap_field(content: Any, default_key: str) -> dict:
        if isinstance(content, dict) and "value" in content:
            if "key" not in content:
                content["key"] = default_key
            return content
        return {
            "key": default_key,
            "value": str(content) if content is not None else "N/A",
            "metrics": {
                "confidence": raw_data.get("overall_confidence", 0.5),
                "flagged": True,
                "reason": "Auto-recovered: LLM failed to provide field metrics."
            }
        }

    # ── 4. Apply wrapper to all sections ─────────────────────────
    for section_name, section_fields in data_block["sections"].items():
        if isinstance(section_fields, dict):
            for key, content in section_fields.items():
                data_block["sections"][section_name][key] = _wrap_field(content, key)

    # ── 5. Apply wrapper to all table rows ───────────────────────
    for i, row in enumerate(data_block["tables"]):
        if isinstance(row, dict):
            for k, v in row.items():
                data_block["tables"][i][k] = _wrap_field(v, k)

    return raw_data
