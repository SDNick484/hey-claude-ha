"""Tests for choosing a profile from the speaking device's area."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

from custom_components.hey_claude.const import (
    CONF_AREA_PROFILES,
    CONF_DEFAULT_PROFILE,
)
from custom_components.hey_claude.profile import area_for_turn, resolve_profile


async def test_area_from_satellite_entity(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    satellite: tuple[str, str],
) -> None:
    """The satellite entity's own area wins over its device's."""
    device_id, entity_id = satellite
    office = area_registry.async_create("Office")
    kitchen = area_registry.async_create("Kitchen")
    device_registry.async_update_device(device_id, area_id=kitchen.id)
    entity_registry.async_update_entity(entity_id, area_id=office.id)

    assert area_for_turn(hass, device_id, entity_id) == office.id


async def test_area_from_satellite_device(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    satellite: tuple[str, str],
) -> None:
    """Without its own area, the satellite uses its device's area."""
    device_id, entity_id = satellite
    office = area_registry.async_create("Office")
    device_registry.async_update_device(device_id, area_id=office.id)

    assert area_for_turn(hass, None, entity_id) == office.id


async def test_area_from_device_id(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    satellite: tuple[str, str],
) -> None:
    """With no satellite entity, the input device's area is used."""
    device_id, _ = satellite
    office = area_registry.async_create("Office")
    device_registry.async_update_device(device_id, area_id=office.id)

    assert area_for_turn(hass, device_id, None) == office.id


async def test_area_none(hass: HomeAssistant, satellite: tuple[str, str]) -> None:
    """No areas anywhere, or unknown IDs, give no area."""
    device_id, entity_id = satellite

    assert area_for_turn(hass, device_id, entity_id) is None
    assert area_for_turn(hass, None, None) is None
    assert area_for_turn(hass, "no-such-device", "assist_satellite.nope") is None


def test_resolve_profile_area_then_default_then_none() -> None:
    """The area's profile, else the default, else none."""
    options = {
        CONF_DEFAULT_PROFILE: "home",
        CONF_AREA_PROFILES: {"office": "work", "den": ""},
    }

    assert resolve_profile(options, "office") == "work"
    assert resolve_profile(options, "kitchen") == "home"
    assert resolve_profile(options, "den") == "home"
    assert resolve_profile(options, None) == "home"
    assert resolve_profile({CONF_DEFAULT_PROFILE: ""}, "office") is None
    assert resolve_profile({}, "office") is None
