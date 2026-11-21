"""Safe application delivery boundary for a future verified Tally webhook.

This module deliberately does not claim a Tally payload schema, implement an
HTTP endpoint, or accept unvalidated webhook requests. A future adapter must
verify Tally's actual webhook configuration and normalize a submission into
the internal notice type below before calling the router.
"""

from dataclasses import dataclass
import logging

import discord

from .logging_config import get_logger
from .settings import Settings


@dataclass(frozen=True, slots=True)
class ValidatedApplicationNotice:
    """Internal delivery contract, not a model of Tally's webhook payload."""

    source_guild_id: int
    delivery_reference: str
    rendered_summary: str


class ApplicationRoutingError(ValueError):
    """Raised when a normalized application cannot be routed safely."""


async def route_validated_application(
    client: discord.Client,
    settings: Settings,
    notice: ValidatedApplicationNotice,
) -> None:
    """Send a pre-validated notice only to its configured server's channel."""
    logger = get_logger(__name__)
    destination_by_guild = {
        settings.main_server.main_guild_id: (
            settings.main_server.main_vip_application_channel_id,
            "main",
        ),
        settings.vip_server.vip_guild_id: (
            settings.vip_server.vip_application_channel_id,
            "vip",
        ),
    }

    if not isinstance(notice.source_guild_id, int) or isinstance(
        notice.source_guild_id, bool
    ):
        raise ApplicationRoutingError("source_guild_id must be an integer")
    destination = destination_by_guild.get(notice.source_guild_id)
    if destination is None:
        logger.warning(
            "application_delivery_rejected",
            extra={
                "event": "application_delivery_rejected",
                "reason": "unknown_source_guild",
            },
        )
        raise ApplicationRoutingError("Application source is not configured")

    if not isinstance(notice.delivery_reference, str) or not (
        1 <= len(notice.delivery_reference.strip()) <= 128
    ):
        raise ApplicationRoutingError("delivery_reference is missing or too long")
    if not isinstance(notice.rendered_summary, str) or not (
        1 <= len(notice.rendered_summary.strip()) <= 1750
    ):
        raise ApplicationRoutingError("rendered_summary is missing or too long")

    channel_id, server_name = destination
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except discord.DiscordException as exc:
            logger.warning(
                "application_delivery_channel_unavailable",
                extra={
                    "event": "application_delivery_channel_unavailable",
                    "server": server_name,
                    "channel_id": channel_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise ApplicationRoutingError(
                "Configured application channel is unavailable"
            ) from exc

    if not isinstance(channel, discord.TextChannel):
        raise ApplicationRoutingError("Configured application channel is not text")
    if channel.guild.id != notice.source_guild_id:
        logger.error(
            "application_delivery_rejected",
            extra={
                "event": "application_delivery_rejected",
                "server": server_name,
                "channel_id": channel_id,
                "reason": "channel_guild_mismatch",
            },
        )
        raise ApplicationRoutingError(
            "Configured application channel belongs to a different server"
        )

    try:
        await channel.send(
            f"New VIP application\n{notice.rendered_summary.strip()}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.DiscordException as exc:
        logger.error(
            "application_delivery_failed",
            extra={
                "event": "application_delivery_failed",
                "server": server_name,
                "channel_id": channel_id,
                "error_type": type(exc).__name__,
            },
        )
        raise ApplicationRoutingError("Discord could not deliver the application") from exc

    logger.info(
        "application_delivery_sent",
        extra={
            "event": "application_delivery_sent",
            "server": server_name,
            "channel_id": channel_id,
        },
    )
