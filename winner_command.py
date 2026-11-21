"""Authorized /create-winner command and VIP Wins delivery."""

import logging
import mimetypes
import re
from urllib.parse import urlsplit

import discord
from discord import app_commands

from .settings import Settings

logger = logging.getLogger(__name__)
_HEX_COLOR = re.compile(r"^(?:#|0x)?([0-9a-fA-F]{6})$")


class WinnerCommandError(ValueError):
    """A user-facing error that prevents unsafe or invalid winner delivery."""


def build_create_winner_command(settings: Settings) -> app_commands.Command:
    """Build the command bound to this bot's configuration."""

    @app_commands.command(
        name="create-winner",
        description="Create a BOOKIE BREAKERS winner announcement.",
    )
    @app_commands.rename(
        admin_name="admin-name",
        amount_won="amount-won",
        custom_embed_color="custom-embed-color",
        vip_link="vip-link",
        betting_slip="betting-slip",
    )
    @app_commands.describe(
        admin_name="Optional authorized admin to mention at the top.",
        announcement="Optional announcement text.",
        amount_won="Optional amount won.",
        custom_embed_color="Optional hex color, such as #2F855A.",
        vip_link="Optional HTTPS VIP link.",
        betting_slip="Optional image attachment shown as the main visual.",
    )
    async def create_winner(
        interaction: discord.Interaction,
        admin_name: discord.User | None = None,
        announcement: str | None = None,
        amount_won: str | None = None,
        custom_embed_color: str | None = None,
        vip_link: str | None = None,
        betting_slip: discord.Attachment | None = None,
    ) -> None:
        # Acknowledge before permission checks, channel lookups, or HTTP calls.
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.user.id not in {
            settings.head_admin_id,
            settings.vip_admin_id,
        }:
            await _respond(interaction, "You are not authorized to use this command.")
            return

        displayed_admin = admin_name or interaction.user
        if displayed_admin.id not in {
            settings.head_admin_id,
            settings.vip_admin_id,
        }:
            await _respond(
                interaction,
                "Admin Name must be the Head/Owner Admin or VIP Admin.",
            )
            return

        if interaction.guild_id != settings.vip_server.vip_guild_id:
            await _respond(interaction, "This command is available in the VIP server.")
            return

        try:
            validated_vip_link = _validated_vip_link(vip_link)
            layout = _build_winner_layout(
                admin_mention=displayed_admin.mention,
                announcement=announcement,
                amount_won=amount_won,
                custom_embed_color=custom_embed_color,
                vip_link=validated_vip_link,
                betting_slip=betting_slip,
            )
            channel = await _resolve_vip_wins_channel(interaction.client, settings)
            await _check_delivery_permissions(interaction.client, channel)
            await channel.send(
                view=layout,
                allowed_mentions=discord.AllowedMentions(
                    everyone=True,
                    users=False,
                    roles=False,
                    replied_user=False,
                ),
            )
        except WinnerCommandError as exc:
            logger.warning(
                "winner_announcement_rejected",
                extra={
                    "event": "winner_announcement_rejected",
                    "guild_id": interaction.guild_id,
                    "reason": str(exc),
                },
            )
            await _respond(interaction, str(exc))
            return
        except discord.Forbidden:
            logger.warning(
                "winner_announcement_forbidden",
                extra={
                    "event": "winner_announcement_forbidden",
                    "guild_id": interaction.guild_id,
                    "channel_id": settings.vip_wins_channel_id,
                },
            )
            await _respond(
                interaction,
                "Discord denied the announcement. Check the bot's channel permissions.",
            )
            return
        except discord.HTTPException as exc:
            logger.error(
                "winner_announcement_failed",
                extra={
                    "event": "winner_announcement_failed",
                    "guild_id": interaction.guild_id,
                    "channel_id": settings.vip_wins_channel_id,
                    "error_type": type(exc).__name__,
                },
            )
            await _respond(
                interaction,
                "Discord could not send the winner announcement. Please try again later.",
            )
            return
        except Exception as exc:
            logger.exception(
                "winner_announcement_unexpected_error",
                extra={
                    "event": "winner_announcement_unexpected_error",
                    "guild_id": interaction.guild_id,
                    "error_type": type(exc).__name__,
                },
            )
            await _respond(
                interaction,
                "The winner announcement could not be completed.",
            )
            return

        await _respond(interaction, "Winner announcement sent to VIP Wins.")

    return create_winner


def _build_winner_layout(
    *,
    admin_mention: str,
    announcement: str | None,
    amount_won: str | None,
    custom_embed_color: str | None,
    vip_link: str | None,
    betting_slip: discord.Attachment | None,
) -> discord.ui.LayoutView:
    accent_color = discord.Color(0x00FF4D)
    if custom_embed_color and custom_embed_color.strip():
        match = _HEX_COLOR.fullmatch(custom_embed_color.strip())
        if match is None:
            raise WinnerCommandError(
                "Custom embed color must be a six-digit hex value, such as #2F855A."
            )
        accent_color = discord.Color(int(match.group(1), 16))

    announcement_text = _clean(announcement)
    text_lines = [admin_mention]
    if announcement_text:
        text_lines.append("")
        text_lines.append(announcement_text)
    text_block = "\n".join(text_lines)

    amount_line = _format_amount_line(amount_won)

    combined_text = "\n".join(
        part for part in (text_block, amount_line) if part is not None
    )
    if len(combined_text) > 4096 or len(text_block) > 4000:
        raise WinnerCommandError(
            "The supplied announcement details are too long for a Discord embed."
        )

    container_items: list[discord.ui.Item] = [
        discord.ui.TextDisplay(admin_mention),
    ]
    if announcement_text:
        container_items.extend(
            [
                discord.ui.Separator(
                    visible=False,
                    spacing=discord.SeparatorSpacing.small,
                ),
                discord.ui.TextDisplay(announcement_text),
            ]
        )
    if amount_line:
        if len(amount_line) > 4000:
            raise WinnerCommandError(
                "The supplied amount details are too long for a Discord message."
            )
        container_items.append(discord.ui.TextDisplay(amount_line))

    if betting_slip is not None:
        content_type = betting_slip.content_type
        if not content_type or not content_type.startswith("image/"):
            content_type = mimetypes.guess_type(betting_slip.filename)[0]
        if not content_type or not content_type.startswith("image/"):
            raise WinnerCommandError("Betting-slip attachment must be an image.")
        container_items.append(
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(media=betting_slip.url)
            )
        )

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.TextDisplay("@everyone"))
    layout.add_item(
        discord.ui.Container(*container_items, accent_color=accent_color)
    )
    if vip_link:
        layout.add_item(
            discord.ui.Container(
                discord.ui.ActionRow(
                    discord.ui.Button(
                        label="VIP • Open VIP",
                        emoji="🔗",
                        style=discord.ButtonStyle.link,
                        url=vip_link,
                    )
                ),
                accent_color=accent_color,
            )
        )
    return layout


def _format_amount_line(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None

    won_value: str | None = None
    paid_value: str | None = None
    parts = re.split(r"\s*\|\s*", value, maxsplit=1)

    if len(parts) == 2:
        won_part, paid_part = parts
        won_match = re.match(r"^\s*(?:amount\s+won|won)\s*:?\s*", won_part, re.I)
        paid_match = re.match(r"^\s*paid\s*:?\s*", paid_part, re.I)
        if paid_match:
            paid_value = paid_part[paid_match.end():].strip()
        else:
            paid_value = paid_part.strip()
        if won_match:
            won_value = won_part[won_match.end():].strip()
        else:
            won_value = won_part.strip()
    else:
        paid_match = re.search(r"\bpaid\b\s*:?\s*", value, re.I)
        if paid_match:
            won_value = value[:paid_match.start()].strip(" \t:|")
            paid_value = value[paid_match.end():].strip()
            won_prefix = re.match(
                r"^\s*(?:amount\s+won|won)\s*:?\s*", won_value, re.I
            )
            if won_prefix:
                won_value = won_value[won_prefix.end():].strip()
        else:
            won_prefix = re.match(
                r"^\s*(?:amount\s+won|won)\s*:?\s*", value, re.I
            )
            paid_prefix = re.match(r"^\s*paid\s*:?\s*", value, re.I)
            if paid_prefix:
                paid_value = value[paid_prefix.end():].strip()
            else:
                won_value = value[won_prefix.end():].strip() if won_prefix else value

    formatted_parts = []
    if won_value:
        formatted_parts.append(
            f"ᴀᴍᴏᴜɴᴛ ᴡᴏɴ: **{discord.utils.escape_markdown(won_value)}**"
        )
    if paid_value:
        formatted_parts.append(
            f"ᴘᴀɪᴅ: **{discord.utils.escape_markdown(paid_value)}**"
        )
    return " | ".join(formatted_parts) or None


def _validated_vip_link(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None

    parsed_link = urlsplit(cleaned)
    if (
        len(cleaned) > 2048
        or parsed_link.scheme != "https"
        or not parsed_link.hostname
        or parsed_link.username is not None
        or parsed_link.password is not None
        or any(character.isspace() for character in cleaned)
    ):
        raise WinnerCommandError("VIP link must be a valid HTTPS URL.")
    return cleaned


async def _resolve_vip_wins_channel(
    client: discord.Client,
    settings: Settings,
) -> discord.TextChannel:
    channel_id = settings.vip_wins_channel_id
    if channel_id is None:
        raise WinnerCommandError(
            "VIP Wins is not configured. Set VIP_WINS_CHANNEL_ID and restart the bot."
        )

    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except discord.NotFound as exc:
            raise WinnerCommandError(
                "The configured VIP Wins destination channel was not found. "
                "Check VIP_WINS_CHANNEL_ID."
            ) from exc
        except discord.Forbidden as exc:
            raise WinnerCommandError(
                "The bot cannot access the configured VIP Wins destination. "
                "Confirm it is in the main server and the bot has channel access."
            ) from exc
        except discord.HTTPException as exc:
            raise WinnerCommandError(
                "Discord could not look up the configured VIP Wins destination."
            ) from exc

    if not isinstance(channel, discord.TextChannel):
        raise WinnerCommandError("VIP_WINS_CHANNEL_ID must point to a text channel.")
    if channel.guild.id != settings.main_server.main_guild_id:
        raise WinnerCommandError(
            "The configured VIP Wins destination must be in the main server."
        )
    return channel


async def _check_delivery_permissions(
    client: discord.Client,
    channel: discord.TextChannel,
) -> None:
    guild = client.get_guild(channel.guild.id)
    if guild is None:
        raise WinnerCommandError(
            "The bot is not connected to the server containing the VIP Wins destination."
        )
    if guild.unavailable:
        raise WinnerCommandError(
            "The server containing the VIP Wins destination is currently unavailable."
        )

    bot_user = client.user
    if bot_user is None:
        raise WinnerCommandError("The bot's Discord identity is not available.")
    bot_member = guild.get_member(bot_user.id)
    if bot_member is None:
        try:
            bot_member = await guild.fetch_member(bot_user.id)
        except discord.NotFound as exc:
            raise WinnerCommandError(
                "The bot is not a member of the server containing the VIP Wins destination."
            ) from exc
        except discord.Forbidden as exc:
            raise WinnerCommandError(
                "Discord would not let the bot verify its membership in the "
                "server containing the VIP Wins destination."
            ) from exc
        except discord.HTTPException as exc:
            raise WinnerCommandError(
                "Discord could not verify the bot's membership in the server "
                "containing the VIP Wins destination."
            ) from exc

    permissions = channel.permissions_for(bot_member)
    if not permissions.view_channel or not permissions.send_messages:
        raise WinnerCommandError(
            "The bot needs View Channel and Send Messages in the VIP Wins destination."
        )
    if not permissions.embed_links:
        raise WinnerCommandError("The bot needs Embed Links in the VIP Wins destination.")
    if not permissions.mention_everyone:
        raise WinnerCommandError(
            "The bot needs Mention Everyone in the VIP Wins destination to notify members."
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


async def _respond(interaction: discord.Interaction, message: str) -> None:
    try:
        await interaction.followup.send(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        logger.warning(
            "winner_command_followup_failed",
            extra={
                "event": "winner_command_followup_failed",
                "error_type": type(exc).__name__,
            },
        )
