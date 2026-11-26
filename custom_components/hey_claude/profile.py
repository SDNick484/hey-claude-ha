"""Pick the relay profile for a turn from the speaking device's area."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_AREA_PROFILES, CONF_DEFAULT_PROFILE


def _device_area(hass: HomeAssistant, device_id: str | None) -> str | None:
    if device_id is None:
        return None
    device = dr.async_get(hass).async_get(device_id)
    return device.area_id if device is not None else None


def area_for_turn(
    hass: HomeAssistant, device_id: str | None, satellite_id: str | None
) -> str | None:
    """Return the area a turn came from.

    The satellite entity's own area wins, then the satellite's device's area,
    then the area of the device Home Assistant says the input came from.
    """
    if satellite_id is not None and (
        entity := er.async_get(hass).async_get(satellite_id)
    ):
        if entity.area_id:
            return entity.area_id
        if area_id := _device_area(hass, entity.device_id):
            return area_id
    return _device_area(hass, device_id)


def resolve_profile(options: Mapping[str, Any], area_id: str | None) -> str | None:
    """Return the area's profile, else the default profile, else None."""
    area_profiles: Mapping[str, str] = options.get(CONF_AREA_PROFILES, {})
    if area_id is not None and (profile := area_profiles.get(area_id)):
        return profile
    return options.get(CONF_DEFAULT_PROFILE) or None
