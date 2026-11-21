"""Validated, environment-backed configuration for both Discord servers."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class MainServerSettings:
    main_guild_id: int
    main_vip_wings_client_id: int
    contact_owner_channel_id: int
    main_vip_application_channel_id: int


@dataclass(frozen=True, slots=True)
class VipServerSettings:
    vip_guild_id: int
    vip_client_id: int
    vip_application_channel_id: int


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str = field(repr=False)
    head_admin_id: int
    vip_admin_id: int
    tally_form_url: str
    vip_wins_channel_id: int | None
    main_server: MainServerSettings
    vip_server: VipServerSettings

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load required settings without logging or exposing secret values."""
        token = _required_value("DISCORD_TOKEN")
        main_server = MainServerSettings(
            main_guild_id=_required_id("MAIN_GUILD_ID"),
            main_vip_wings_client_id=_required_id("MAIN_VIP_WINGS_CLIENT_ID"),
            contact_owner_channel_id=_required_id("CONTACT_OWNER_CHANNEL_ID"),
            main_vip_application_channel_id=_required_id(
                "MAIN_VIP_APPLICATION_CHANNEL_ID"
            ),
        )
        vip_server = VipServerSettings(
            vip_guild_id=_required_id("VIP_GUILD_ID"),
            vip_client_id=_required_id("VIP_CLIENT_ID"),
            vip_application_channel_id=_required_id("VIP_APPLICATION_CHANNEL_ID"),
        )
        if main_server.main_guild_id == vip_server.vip_guild_id:
            raise ValueError("MAIN_GUILD_ID and VIP_GUILD_ID must be different servers")

        tally_form_url = _required_value("TALLY_FORM_URL")
        parsed_url = urlsplit(tally_form_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("TALLY_FORM_URL must be an HTTPS URL")

        return cls(
            discord_token=token,
            head_admin_id=_required_id("HEAD_ADMIN_ID"),
            vip_admin_id=_required_id("VIP_ADMIN_ID"),
            tally_form_url=tally_form_url,
            vip_wins_channel_id=_optional_id("VIP_WINS_CHANNEL_ID"),
            main_server=main_server,
            vip_server=vip_server,
        )


def _required_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def _required_id(name: str) -> int:
    value = _required_value(name)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"Environment variable {name} must be a positive integer")
    return parsed


def _optional_id(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"Environment variable {name} must be a positive integer")
    return parsed
