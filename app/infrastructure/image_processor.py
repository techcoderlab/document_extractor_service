# ─────────────────────────────────────────────────────
# Module   : app/infrastructure/image_processor.py
# Layer    : Infrastructure
# Pillar   : P4 (Performance), P8 (Code Quality)
# Complexity: O(N) time, O(N) space (where N is pixel count)
# ─────────────────────────────────────────────────────

import io
from PIL import Image
import structlog

logger = structlog.get_logger("app")

# Maximum dimension (width or height) to send to the LLM. 
# 1536px is optimal for Gemini/GPT-4o vision token sizing.
MAX_DIMENSION = 1536 
JPEG_QUALITY = 85

def optimize_image_for_llm(raw_bytes: bytes, preserve_color: bool = False) -> tuple[bytes, str]:
    """
    Pre-processes the image to reduce LLM token cost and API latency.
    - Resizes large images while maintaining aspect ratio.
    - Converts to Grayscale (L) to reduce payload size (unless preserve_color is True).
    - Normalizes format to JPEG.
    
    Args:
        raw_bytes: Raw image bytes.
        preserve_color: If True, skip grayscale conversion (needed for passports, IDs with photos).
    """
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            # 1. Strip Alpha Channel / Normalize to RGB
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
                
            # 2. Resize to optimal vision token boundaries
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            
            # 3. Convert to Grayscale to save bandwidth/tokens (skip for color-dependent docs)
            if not preserve_color:
                img = img.convert("L")
            
            # 4. Export to optimized JPEG
            output_buffer = io.BytesIO()
            img.save(output_buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            
            optimized_bytes = output_buffer.getvalue()
            
            logger.info(
                "Image optimized for LLM", 
                original_size=len(raw_bytes), 
                new_size=len(optimized_bytes),
                reduction_pct=round((1 - len(optimized_bytes)/len(raw_bytes)) * 100, 1),
                grayscale=not preserve_color
            )
            
            return optimized_bytes, "image/jpeg"
            
    except Exception as e:
        logger.error("Failed to optimize image, falling back to original", error=str(e))
        return raw_bytes, "image/jpeg"  # Safe fallback