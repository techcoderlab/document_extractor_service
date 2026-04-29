# ─────────────────────────────────────────────────────
# Module   : app/infrastructure/sheets_client.py
# Layer    : Infrastructure
# Pillar   : P1 (Architecture), P3 (Concurrency), P9 (Data)
# Complexity: O(1) time, O(1) space (Network bound)
# ─────────────────────────────────────────────────────

import json
import base64
import asyncio
from typing import Any
import structlog

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.domain.entities import ExtractionJob
from app.core.config import settings
from app.core.exceptions import SheetPersistenceError

logger = structlog.get_logger("app")

def _sync_append_row(spreadsheet_id: str, row: list[Any], b64_cred: str) -> None:
    """
    Synchronous function to append a row to Google Sheets.
    Isolated so it can be safely offloaded to a thread pool via asyncio.to_thread.
    """
    try:
        cred_bytes = base64.b64decode(b64_cred)
        cred_dict = json.loads(cred_bytes)
        creds = Credentials.from_service_account_info(
            cred_dict, 
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        
        service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        body = {"values": [row]}
        
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, 
            range="A2",
            valueInputOption="RAW", 
            insertDataOption="INSERT_ROWS", 
            body=body
        ).execute()
        
    except Exception as e:
        raise SheetPersistenceError(f"Failed to communicate with Sheets API: {str(e)}")

async def save_extraction_to_sheets(job: ExtractionJob) -> None:
    """
    Infrastructure implementation of the persistence port.
    Converts domain entities to flat tabular data and writes async.
    Works with ANY document type — the generic sections/tables schema
    is flattened into a JSON string for the spreadsheet.
    """
    if not settings.GOOGLE_SPREADSHEET_ID or not settings.GOOGLE_SERVICE_ACCOUNT_B64:
        logger.warning("Google Sheets credentials missing. Skipping persistence.")
        return
    
    # Flatten the generic sections/tables data into a single JSON column
    # final_data = flatten_dict(job.result.data.model_dump()) if job.result else {}
    final_data = job.result.data.model_dump() if job.result else {}
    
    row = [
        str(job.job_id),
        job.created_at.isoformat(),
        job.completed_at.isoformat() if job.completed_at else "N/A",
        job.discord_user_id,
        job.provider,
        job.model,
        
        str(job.result.token_usage.prompt_tokens) if job.result and job.result.token_usage else "0",
        str(job.result.token_usage.completion_tokens) if job.result and job.result.token_usage else "0",
        str(job.result.token_usage.total_tokens) if job.result and job.result.token_usage else "0",
        
        job.result.document_type if job.result else "N/A",
        str(job.result.overall_confidence) if job.result else "0",
        str(job.result.requires_human_review) if job.result else "False",
        json.dumps(final_data),
        job.error_message or ""
    ]
    
    # Execute the blocking Google API call in a separate thread (P3 Concurrency)
    await asyncio.to_thread(_sync_append_row, settings.GOOGLE_SPREADSHEET_ID, row, settings.GOOGLE_SERVICE_ACCOUNT_B64)
    
def flatten_dict(d: dict, parent_key: str = '', sep: str = '.') -> dict:
    """
    Recursively flattens a hierarchical dictionary for spreadsheet storage.
    Example: {'header': {'date': {'value': '2026'}}} -> {'header.date': '2026'}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            # If it's our specialized node, just grab the value
            if "value" in v and "metrics" in v:
                items.append((new_key, v["value"]))
            else:
                items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Stringify lists safely
            items.append((new_key, json.dumps(v)))
        else:
            items.append((new_key, v))
    return dict(items)

# Bind the abstract port from Step 3 to this concrete implementation (P1 Architecture)
import app.application.ports
app.application.ports.save_extraction_to_sheets = save_extraction_to_sheets