# ─────────────────────────────────────────────────────
# Module   : app/application/prompt_registry.py
# Layer    : Application
# Pillar   : P1 (Architecture), P4 (Performance / Token Efficiency)
# ─────────────────────────────────────────────────────
#
# EXTENDING THIS REGISTRY:
#   To add a new document type, simply add a new key to PROMPT_REGISTRY.
#   The prompt MUST instruct the LLM to use the generic output schema:
#     { "document_type": "...", "overall_confidence": ..., "requires_human_review": ...,
#       "data": { "sections": { "section_name": { "field": {...} } }, "tables": [...] } }
#   Keep prompts short and focused — every token in the prompt costs money.
# ─────────────────────────────────────────────────────

# Shared schema fragment — referenced by all prompts to enforce uniform output.
# Kept minimal to reduce input token cost.
_SCHEMA_FRAGMENT = """{
  "document_type": "string",
  "overall_confidence": float,
  "requires_human_review": boolean,
  "data": {
    "sections": {
      "section_name": {
        "field_name": { "key": "field_name", "value": "...", "metrics": { "confidence": 0.9, "flagged": false, "reason": null } }
      }
    },
    "tables": [
      { "column_a": { "key": "column_a", "value": "...", "metrics": { "confidence": 0.9, "flagged": false, "reason": null } } }
    ]
  }
}"""

# ── Document Type Hints (used for color preservation decisions) ──
# Types where the image processor should preserve color
COLOR_REQUIRED_TYPES = frozenset({"passport", "id_card", "legacy"})

# ── Prompt Registry ──────────────────────────────────────────────

PROMPT_REGISTRY: dict[str, str] = {

    # ── Universal / Auto-Classify ────────────────────────────────
    "auto": f"""Extract all data from this document image. First classify its type, then extract every relevant field.
Output ONLY valid JSON matching this schema:
{_SCHEMA_FRAGMENT}
Group fields into logical sections. Use "tables" for repeating row data (line items, cargo, transactions). Keep section/field names lowercase_snake_case.""",

    # ── Financial Documents ──────────────────────────────────────
    "receipt": f"""Extract data from this RECEIPT image.
Sections: "merchant_info" (merchant_name, date, payment_method), "summary" (subtotal, tax, total).
Tables: line items with description, quantity, unit_price, amount.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",

    "invoice": f"""Extract data from this INVOICE image.
Sections: "vendor_info" (vendor_name, address, contact), "invoice_details" (invoice_number, date, due_date, po_number), "payment" (subtotal, tax, discount, total, payment_terms).
Tables: line items with description, quantity, unit_price, amount.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",

    # ── Identity Documents ───────────────────────────────────────
    "passport": f"""Extract data from this PASSPORT image.
Sections: "personal_info" (full_name, date_of_birth, sex, nationality, place_of_birth), "document_info" (passport_number, issuing_country, issue_date, expiry_date, mrz_line_1, mrz_line_2).
Tables: not applicable — leave empty.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",

    "id_card": f"""Extract data from this ID CARD / National Identity Document image.
Sections: "personal_info" (full_name, date_of_birth, sex, address), "document_info" (id_number, issuing_authority, issue_date, expiry_date).
Tables: not applicable — leave empty.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",

    # ── Logistics / Shipping ─────────────────────────────────────
    "bill_of_lading": f"""Extract data from this BILL OF LADING image.
Sections: "shipper" (name, address), "consignee" (name, address), "shipping_details" (vessel_name, voyage_number, port_of_loading, port_of_discharge, date_of_shipment, bill_of_lading_number).
Tables: cargo items with description, quantity, weight, volume, marks_and_numbers.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",

    # ── Legacy / Degraded ────────────────────────────────────────
    "legacy": f"""Extract ALL readable text and data from this OLD or DEGRADED document image.
Group data into logical sections based on content. Flag any field where text is partially illegible.
Output ONLY valid JSON:
{_SCHEMA_FRAGMENT}""",
}


def get_prompt(doc_type_hint: str = "auto") -> str:
    """
    Returns the appropriate system prompt for the given document type hint.
    Falls back to 'auto' for unrecognized types.
    """
    return PROMPT_REGISTRY.get(doc_type_hint.lower(), PROMPT_REGISTRY["auto"])


def get_supported_types() -> list[str]:
    """Returns all registered document type keys for help text / validation."""
    return sorted(PROMPT_REGISTRY.keys())


def requires_color(doc_type_hint: str) -> bool:
    """Returns True if the document type requires color image preservation."""
    return doc_type_hint.lower() in COLOR_REQUIRED_TYPES
