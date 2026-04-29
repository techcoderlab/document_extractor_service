# ─────────────────────────────────────────────────────
# Module   : app/infrastructure/discord_bot.py
# Layer    : Infrastructure / Presentation
# Pillar   : P2 (Security), P3 (Concurrency), P8 (Code Quality)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

import json
import discord
from discord.ext import commands
import structlog
from datetime import datetime, timezone

from app.core.config import settings
from app.core.exceptions import (
    ERROR_FILE_TOO_LARGE, 
    ERROR_UNSUPPORTED_TYPE, 
)
from app.application.orchestrator import process_discord_extraction
from app.application.prompt_registry import get_supported_types

logger = structlog.get_logger("app")

# Initialize Bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

@bot.event
async def on_ready() -> None:
    """Fired when the bot successfully connects to Discord."""
    logger.info("Discord bot connected and ready", user=bot.user.name if bot.user else "Unknown")


# ── !extract <type> command (Option C: power-user document type hint) ──
@bot.command(name="extract")
async def extract_command(ctx: commands.Context, doc_type: str = "auto") -> None:
    """
    Explicit extraction command with optional document type hint.
    Usage: !extract passport  (attach image to the same message)
           !extract receipt
           !extract auto
    """
    supported = get_supported_types()
    
    if doc_type.lower() not in supported:
        type_list = ", ".join(f"`{t}`" for t in supported)
        await ctx.reply(f"❌ Unknown document type `{doc_type}`. Supported: {type_list}")
        return
    
    if not ctx.message.attachments:
        await ctx.reply("❌ Please attach an image to your message.\n**Usage:** `!extract passport` (with an image attached)")
        return
    
    attachment = ctx.message.attachments[0]
    
    # Security guards
    if attachment.size > settings.MAX_IMAGE_SIZE_BYTES:
        await ctx.reply(ERROR_FILE_TOO_LARGE.format(size=attachment.size / (1024 * 1024)))
        return
    
    mime_type = attachment.content_type
    if mime_type not in ALLOWED_MIMES:
        await ctx.reply(ERROR_UNSUPPORTED_TYPE.format(mime=mime_type or "unknown"))
        return
    
    async with ctx.typing():
        try:
            image_bytes = await attachment.read()
            job = await process_discord_extraction(
                user_id=str(ctx.author.id),
                channel_id=str(ctx.channel.id),
                message_id=str(ctx.message.id),
                image_bytes=image_bytes,
                mime_type=mime_type,
                provider=settings.DEFAULT_PROVIDER,
                model=settings.DEFAULT_MODEL,
                doc_type_hint=doc_type.lower()
            )
            
            if job.status == "SUCCESS" and job.result:
                embed = create_human_friendly_embed(job)
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(f"❌ **Extraction failed:** {job.error_message}")
        except Exception as e:
            logger.exception("Unhandled exception during !extract command")
            await ctx.reply("⚠️ An unexpected internal error occurred while processing the image.")


# ── !doctypes command (list supported types) ──
@bot.command(name="doctypes")
async def doctypes_command(ctx: commands.Context) -> None:
    """Lists all supported document types."""
    supported = get_supported_types()
    type_list = "\n".join(f"• `{t}`" for t in supported)
    await ctx.reply(f"📋 **Supported document types:**\n{type_list}\n\n**Usage:** `!extract <type>` with an image attached, or just drop an image for auto-detection.")


@bot.event
async def on_message(message: discord.Message) -> None:
    """
    Main ingestion point for Discord messages. 
    For plain image uploads (no command), uses 'auto' document type detection.
    """
    # 1. Ignore bot's own messages
    if message.author == bot.user:
        return

    # 2. Channel filtering (if configured)
    if settings.DISCORD_WATCH_CHANNEL_ID and str(message.channel.id) != settings.DISCORD_WATCH_CHANNEL_ID:
        return

    # CRITICAL: Process commands first (so !extract is handled by the command handler)
    await bot.process_commands(message)
    
    # If the message starts with a command prefix, stop here (command handler takes over)
    if message.content.startswith("!"):
        return

    # 3. Ensure message has attachments (plain image drop without a command)
    if not message.attachments:
        return

    attachment = message.attachments[0]

    # 4. P2 Security Guard: Reject > 5MB BEFORE downloading bytes
    if attachment.size > settings.MAX_IMAGE_SIZE_BYTES:
        logger.warning("Rejected file: exceeds size limit", size=attachment.size, user=str(message.author.id))
        await message.reply(ERROR_FILE_TOO_LARGE.format(size=attachment.size / (1024 * 1024)))
        return

    # 5. P2 Security Guard: Reject unsupported mime types
    mime_type = attachment.content_type
    if mime_type not in ALLOWED_MIMES:
        logger.warning("Rejected file: invalid mime type", mime=mime_type, user=str(message.author.id))
        await message.reply(ERROR_UNSUPPORTED_TYPE.format(mime=mime_type or "unknown"))
        return

    # 6. Process the extraction with typing indicator (auto mode)
    async with message.channel.typing():
        try:
            image_bytes = await attachment.read()
            
            job = await process_discord_extraction(
                user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                message_id=str(message.id),
                image_bytes=image_bytes,
                mime_type=mime_type,
                provider=settings.DEFAULT_PROVIDER,
                model=settings.DEFAULT_MODEL,
                doc_type_hint="auto"
            )

            # 7. Format Contextual Response
            if job.status == "SUCCESS" and job.result:
                embed = create_human_friendly_embed(job)
                await message.reply(embed=embed)
            else:
                await message.reply(f"❌ **Extraction failed:** {job.error_message}")
                
        except Exception as e:
            logger.exception("Unhandled exception during Discord message processing")
            await message.reply("⚠️ An unexpected internal error occurred while processing the image.")


def create_human_friendly_embed(job) -> discord.Embed:
    """
    Dynamically renders extraction results into a Discord Embed.
    Adapts to ANY document type — renders whatever sections and tables the LLM returned.
    """
    res = job.result
    
    # Color logic based on confidence and human review flags
    if res.requires_human_review:
        color = discord.Color.red() if res.overall_confidence < 0.6 else discord.Color.gold()
        status_icon = "⚠️ Review Required"
    else:
        color = discord.Color.brand_green()
        status_icon = "✅ Verified Extraction"

    embed = discord.Embed(
        title=f"📄 Document Extracted: {res.document_type}",
        description=f"**Status:** {status_icon}\n**Confidence:** {res.overall_confidence:.1%}",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )

    # Helper to safely extract values from the nested structure
    def extract_val(field: dict) -> str:
        val = field.get("value", "N/A")
        flag = " 🚩" if field.get("metrics", {}).get("flagged") else ""
        return f"{val}{flag}"

    # ── Dynamically render ALL sections ──────────────────────────
    data_dict = res.data.model_dump()
    sections = data_dict.get("sections", {})
    
    # Discord Limit: Max 25 fields per embed
    field_count = 0
    max_fields = 25
    truncated = False
    
    for section_name, section_fields in sections.items():
        if not section_fields:
            continue
            
        if field_count >= max_fields - 1: # Leave room for a possible table or footer notice
            truncated = True
            break

        # Add a visual separator with the section title
        embed.add_field(name=f"─── {section_name.replace('_', ' ').title()} ───", value="\u200b", inline=False)
        field_count += 1
        
        for key, field in section_fields.items():
            if field_count >= max_fields - 1:
                truncated = True
                break
            embed.add_field(
                name=key.replace("_", " ").title(), 
                value=extract_val(field), 
                inline=True
            )
            field_count += 1

    # ── Dynamically render table rows ────────────────────────────
    tables = data_dict.get("tables", [])
    if tables and field_count < max_fields:
        # Build column headers from the first row's keys
        first_row = tables[0]
        col_keys = list(first_row.keys())
        
        # Build a formatted text block
        table_str = "```text\n"
        for idx, row in enumerate(tables, 1):
            parts = []
            for col in col_keys:
                # Get value and truncate for table cell
                val = str(row.get(col, {}).get("value", "—"))[:20]
                parts.append(val)
            table_str += f"{idx}. {' | '.join(parts)}\n"
        table_str += "```"
        
        # Discord embeds have a 1024 char limit per field value
        if len(table_str) > 1024:
            table_str = table_str[:1020] + "\n```"
        
        embed.add_field(name="📊 Table Data", value=table_str, inline=False)
        field_count += 1

    # Add truncation notice if any data was left out
    if truncated:
        embed.add_field(
            name="ℹ️ Note", 
            value="Some fields were truncated due to Discord's embed limits. All data is preserved in Google Sheets.", 
            inline=False
        )

    tokens = res.token_usage.total_tokens if res.token_usage else 0
    embed.set_footer(
        text=f"ID: {str(job.job_id).split('-')[0]} • Engine: {job.provider} • 🪙 Tokens: {tokens:,}"
    )
    return embed