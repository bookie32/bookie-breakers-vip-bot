"""Idempotent setup for the bot-managed contact and application panels."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import discord

from .logging_config import get_logger
from .settings import Settings


@dataclass(frozen=True, slots=True)
class PanelSpec:
    key: str
    guild_id: int
    channel_id: int
    embed: discord.Embed
    view_factory: Callable[[], discord.ui.View]


class _PanelLookupUnavailable(RuntimeError):
    """Panel history could not be checked safely."""


class ContactAdminView(discord.ui.View):
    def __init__(self, vip_admin_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="📩 Contact Admin",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/users/{vip_admin_id}",
            )
        )


class VipApplicationView(discord.ui.View):
    def __init__(self, tally_form_url: str) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="🎫 VIP Application",
                style=discord.ButtonStyle.link,
                url=tally_form_url,
            )
        )


class PanelManager:
    def __init__(self, client: discord.Client, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.logger = get_logger(__name__)
        self.state_path = Path(__file__).resolve().parents[1] / "state" / "panels.json"
        self._state_lock = asyncio.Lock()
        self._message_ids = self._load_state()

    def _load_state(self) -> dict[str, int]:
        try:
            raw_state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw_state, dict):
                raise ValueError("Panel state must be a JSON object")
            return {
                key: value
                for key, value in raw_state.items()
                if isinstance(key, str) and isinstance(value, int) and value > 0
            }
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, ValueError):
            self.logger.warning(
                "panel_state_unavailable",
                extra={
                    "event": "panel_state_unavailable",
                    "reason": "state_file_invalid_or_unreadable",
                },
            )
            return {}

    async def ensure_all(self) -> None:
        async with self._state_lock:
            for panel in self._panel_specs():
                try:
                    await self._ensure_panel(panel)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.logger.error(
                        "panel_setup_failed",
                        extra={
                            "event": "panel_setup_failed",
                            "panel": panel.key,
                            "channel_id": panel.channel_id,
                            "error_type": type(exc).__name__,
                        },
                    )

    def _panel_specs(self) -> tuple[PanelSpec, ...]:
        main = self.settings.main_server
        vip = self.settings.vip_server
        contact_embed = discord.Embed(
            title="Contact the Admin Team",
            description=(
                "Use the button below to open the VIP Admin’s Discord profile.\n\n"
                f"Head/Owner Admin: <@{self.settings.head_admin_id}>"
            ),
            color=discord.Color.blurple(),
        )
        contact_embed.set_footer(text="BOOKIE BREAKERS • Support")

        main_application_embed = discord.Embed(
            title="VIP Application",
            description="Use the button below to open the VIP application form.",
            color=discord.Color.gold(),
        )
        main_application_embed.set_footer(text="BOOKIE BREAKERS • Applications")

        vip_application_embed = discord.Embed(
            title="VIP Application",
            description="Use the button below to open the VIP application form.",
            color=discord.Color.gold(),
        )
        vip_application_embed.set_footer(text="BOOKIE BREAKERS • Applications")

        return (
            PanelSpec(
                key="main-contact",
                guild_id=main.main_guild_id,
                channel_id=main.contact_owner_channel_id,
                embed=contact_embed,
                view_factory=lambda: ContactAdminView(self.settings.vip_admin_id),
            ),
            PanelSpec(
                key="main-vip-application",
                guild_id=main.main_guild_id,
                channel_id=main.main_vip_application_channel_id,
                embed=main_application_embed,
                view_factory=lambda: VipApplicationView(self.settings.tally_form_url),
            ),
            PanelSpec(
                key="vip-application",
                guild_id=vip.vip_guild_id,
                channel_id=vip.vip_application_channel_id,
                embed=vip_application_embed,
                view_factory=lambda: VipApplicationView(self.settings.tally_form_url),
            ),
        )

    async def _ensure_panel(self, panel: PanelSpec) -> None:
        channel = await self._resolve_channel(panel)
        if channel is None:
            return

        message = await self._find_existing_message(channel, panel)
        if message is None:
            message = await channel.send(
                embed=panel.embed,
                view=panel.view_factory(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            action = "created"
        else:
            await message.edit(
                content=None,
                embed=panel.embed,
                view=panel.view_factory(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            action = "updated"

        self._message_ids[panel.key] = message.id
        self._save_state()
        self.logger.info(
            "panel_ready",
            extra={
                "event": "panel_ready",
                "panel": panel.key,
                "channel_id": panel.channel_id,
                "reason": action,
            },
        )

    async def _resolve_channel(
        self, panel: PanelSpec
    ) -> discord.TextChannel | None:
        channel = self.client.get_channel(panel.channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(panel.channel_id)
            except discord.NotFound:
                self._log_channel_unavailable(panel, "channel_not_found")
                return None
            except discord.Forbidden:
                self._log_channel_unavailable(panel, "channel_access_forbidden")
                return None
            except discord.HTTPException as exc:
                self._log_channel_unavailable(
                    panel, f"discord_http_{exc.status}"
                )
                return None

        if not isinstance(channel, discord.TextChannel):
            self._log_channel_unavailable(panel, "configured_channel_is_not_text")
            return None
        if channel.guild.id != panel.guild_id:
            self._log_channel_unavailable(panel, "channel_belongs_to_wrong_guild")
            return None
        return channel

    async def _find_existing_message(
        self, channel: discord.TextChannel, panel: PanelSpec
    ) -> discord.Message | None:
        bot_user = self.client.user
        if bot_user is None:
            return None

        stored_id = self._message_ids.get(panel.key)
        if stored_id is not None:
            try:
                stored_message = await channel.fetch_message(stored_id)
            except discord.NotFound:
                stored_message = None
            except discord.Forbidden:
                self._log_channel_unavailable(panel, "history_access_forbidden")
                raise _PanelLookupUnavailable from None
            except discord.HTTPException:
                self._log_channel_unavailable(panel, "stored_panel_lookup_failed")
                raise _PanelLookupUnavailable from None
            if stored_message is not None and self._is_our_panel(
                stored_message, bot_user.id, panel
            ):
                return stored_message

        try:
            async for message in channel.history(limit=100):
                if self._is_our_panel(message, bot_user.id, panel):
                    return message
        except discord.Forbidden:
            # Fail closed rather than risk creating another panel when its
            # existing message cannot be checked.
            self._log_channel_unavailable(panel, "history_access_forbidden")
            raise _PanelLookupUnavailable from None
        except discord.HTTPException as exc:
            self._log_channel_unavailable(
                panel, f"history_lookup_http_{exc.status}"
            )
            raise _PanelLookupUnavailable from None
        return None

    @staticmethod
    def _is_our_panel(
        message: discord.Message, bot_user_id: int, panel: PanelSpec
    ) -> bool:
        if message.author.id != bot_user_id:
            return False
        footer_texts = {
            embed.footer.text
            for embed in message.embeds
            if embed.footer and embed.footer.text
        }
        expected_footer = (
            "BOOKIE BREAKERS • Support"
            if panel.key == "main-contact"
            else "BOOKIE BREAKERS • Applications"
        )
        return expected_footer in footer_texts

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(self._message_ids, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.state_path)
        except OSError as exc:
            self.logger.error(
                "panel_state_save_failed",
                extra={
                    "event": "panel_state_save_failed",
                    "error_type": type(exc).__name__,
                },
            )

    def _log_channel_unavailable(self, panel: PanelSpec, reason: str) -> None:
        self.logger.warning(
            "panel_channel_unavailable",
            extra={
                "event": "panel_channel_unavailable",
                "panel": panel.key,
                "channel_id": panel.channel_id,
                "reason": reason,
            },
        )
