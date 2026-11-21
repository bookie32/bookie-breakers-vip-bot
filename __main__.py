"""Application entry point for the BOOKIE BREAKERS Discord bot."""

import discord
from discord import app_commands
import sys

from .logging_config import configure_logging, get_logger
from .panels import PanelManager
from .settings import Settings
from .winner_command import build_create_winner_command


class BookieBreakersBot(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(
            build_create_winner_command(settings),
            guild=discord.Object(id=settings.vip_server.vip_guild_id),
        )
        self.panel_manager = PanelManager(self, settings)
        self.logger = get_logger(__name__)

    async def setup_hook(self) -> None:
        guild = discord.Object(id=self.settings.vip_server.vip_guild_id)
        application_id = self.application_id
        command = self.tree.get_command("create-winner", guild=guild)
        if application_id is None or command is None:
            self.logger.error(
                "discord_command_registration_failed",
                extra={
                    "event": "discord_command_registration_failed",
                    "guild_id": self.settings.vip_server.vip_guild_id,
                    "command_name": "create-winner",
                    "error_type": "application_or_local_command_unavailable",
                },
            )
            return

        try:
            # Tree.sync replaces every command for the application in this
            # guild. Upsert only this command so unrelated remote commands stay
            # untouched while restarts update rather than duplicate it.
            remote_commands = await self.http.get_guild_commands(
                application_id,
                self.settings.vip_server.vip_guild_id,
            )
            existing_command = next(
                (
                    remote
                    for remote in remote_commands
                    if remote.get("name") == "create-winner"
                ),
                None,
            )
            payload = command.to_dict(self.tree)
            if existing_command is None:
                await self.http.upsert_guild_command(
                    application_id,
                    self.settings.vip_server.vip_guild_id,
                    payload,
                )
                command_status = "created"
            else:
                await self.http.edit_guild_command(
                    application_id,
                    self.settings.vip_server.vip_guild_id,
                    existing_command["id"],
                    payload,
                )
                command_status = "updated"
        except discord.DiscordException as exc:
            self.logger.error(
                "discord_command_registration_failed",
                extra={
                    "event": "discord_command_registration_failed",
                    "guild_id": self.settings.vip_server.vip_guild_id,
                    "error_type": type(exc).__name__,
                },
            )
            return

        self.logger.info(
            "discord_command_registration_succeeded",
            extra={
                "event": "discord_command_registration_succeeded",
                "guild_id": self.settings.vip_server.vip_guild_id,
                "command_name": "create-winner",
                "command_status": command_status,
            },
        )

    async def on_ready(self) -> None:
        if self.user is None:
            self.logger.error(
                "gateway_ready_without_user",
                extra={"event": "gateway_ready_without_user"},
            )
            return

        self.logger.info(
            "discord_gateway_ready",
            extra={
                "event": "discord_gateway_ready",
                "bot_user_id": self.user.id,
                "connected_guild_count": len(self.guilds),
            },
        )
        self._log_configured_guild("main", self.settings.main_server.main_guild_id)
        self._log_configured_guild("vip", self.settings.vip_server.vip_guild_id)

        # Channel setup is isolated per panel; an unavailable channel does not
        # prevent the client from remaining connected or setting up other panels.
        await self.panel_manager.ensure_all()

    async def on_disconnect(self) -> None:
        self.logger.warning(
            "discord_gateway_disconnected",
            extra={"event": "discord_gateway_disconnected"},
        )

    async def on_resumed(self) -> None:
        self.logger.info(
            "discord_gateway_resumed",
            extra={"event": "discord_gateway_resumed"},
        )

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        current_error = sys.exception()
        self.logger.error(
            "discord_event_handler_failed",
            extra={
                "event": "discord_event_handler_failed",
                "event_method": event_method,
                "error_type": (
                    type(current_error).__name__
                    if current_error is not None
                    else "UnknownError"
                ),
            },
        )

    def _log_configured_guild(self, server_name: str, guild_id: int) -> None:
        guild = self.get_guild(guild_id)
        fields: dict[str, object] = {
            "event": "configured_guild_status",
            "server": server_name,
            "guild_id": guild_id,
            "available": guild is not None and not guild.unavailable,
        }
        if guild is not None:
            fields["guild_name"] = guild.name
        self.logger.info(
            "configured Discord server status",
            extra=fields,
        )


def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    try:
        settings = Settings.from_environment()
    except ValueError as exc:
        # Configuration errors only contain variable names and validation
        # reasons; never include secret values in an error message.
        logger.error(
            "startup_configuration_invalid",
            extra={
                "event": "startup_configuration_invalid",
                "reason": str(exc),
            },
        )
        return 2

    logger.info(
        "bot_starting",
        extra={"event": "bot_starting", "configured_servers": 2},
    )
    client = BookieBreakersBot(settings)
    try:
        client.run(
            settings.discord_token,
            reconnect=True,
            log_handler=None,
        )
    except discord.LoginFailure:
        logger.error(
            "discord_login_failed",
            extra={"event": "discord_login_failed"},
        )
        return 1
    except (discord.DiscordException, OSError) as exc:
        logger.error(
            "bot_stopped_after_runtime_error",
            extra={
                "event": "bot_stopped_after_runtime_error",
                "error_type": type(exc).__name__,
            },
        )
        return 1
    except KeyboardInterrupt:
        logger.info(
            "bot_shutdown_requested",
            extra={"event": "bot_shutdown_requested"},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
