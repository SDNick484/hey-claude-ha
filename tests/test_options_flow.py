"""Tests for the options flow: default and per-area profiles."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hey_claude.const import (
    CONF_AREA_PROFILES,
    CONF_DEFAULT_PROFILE,
)
from custom_components.hey_claude.profile import resolve_profile


def _room_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Return {area name: suggested value} from the form's rooms section."""
    rooms = result["data_schema"].schema["rooms"]
    assert isinstance(rooms, section)
    return {
        str(marker): (marker.description or {}).get("suggested_value")
        for marker in rooms.schema.schema
    }


async def test_options_flow_saves_by_area_id(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Profiles are entered by area name and stored by area ID."""
    office = area_registry.async_create("Office")
    area_registry.async_create("Kitchen")
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert _room_fields(result) == {"Office": None, "Kitchen": None}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_PROFILE: " home ",
            "rooms": {"Office": " office ", "Kitchen": ""},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_DEFAULT_PROFILE: "home",
        CONF_AREA_PROFILES: {office.id: "office"},
    }


async def test_options_flow_blank_removes(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Clearing a field removes that profile."""
    office = area_registry.async_create("Office")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_DEFAULT_PROFILE: "home", CONF_AREA_PROFILES: {office.id: "x"}},
    )

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert _room_fields(result) == {"Office": "x"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEFAULT_PROFILE: "", "rooms": {"Office": ""}}
    )

    assert mock_config_entry.options == {
        CONF_DEFAULT_PROFILE: "",
        CONF_AREA_PROFILES: {},
    }


async def test_options_drop_deleted_areas(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A deleted area's profile is ignored, then dropped on the next save."""
    office = area_registry.async_create("Office")
    garage = area_registry.async_create("Garage")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_AREA_PROFILES: {office.id: "o", garage.id: "g"}},
    )
    area_registry.async_delete(garage.id)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert _room_fields(result) == {"Office": "o"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"rooms": {"Office": "o"}}
    )

    assert mock_config_entry.options[CONF_AREA_PROFILES] == {office.id: "o"}


async def test_profile_survives_area_rename(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Renaming an area keeps its profile, shown under the new name."""
    office = area_registry.async_create("Office")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AREA_PROFILES: {office.id: "o"}}
    )
    area_registry.async_update(office.id, name="Study")

    assert resolve_profile(mock_config_entry.options, office.id) == "o"
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert _room_fields(result) == {"Study": "o"}


async def test_options_flow_without_areas(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """With no areas, the form has only the default profile."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert "rooms" not in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DEFAULT_PROFILE: "home"}
    )

    assert mock_config_entry.options == {
        CONF_DEFAULT_PROFILE: "home",
        CONF_AREA_PROFILES: {},
    }
