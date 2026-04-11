"""Heating Temperature Guardian.

Monitors the Heating Day temperature setting and automatically reverts it
to the desired value when an external change is detected.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import EconetApi
from .change_detector import ChangeDetector
from .const import DOMAIN, NUMBER_DEFINITIONS, SERVICE_DATABASE

_LOGGER = logging.getLogger(__name__)

GUARDIAN_PARAM = "Circuit1ComfortTemp"
GUARDIAN_INDEX = NUMBER_DEFINITIONS[GUARDIAN_PARAM]["param_index"]


class HeatingGuardian:
    """Watches Heating Day Temperature and reverts unauthorized changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: EconetApi,
        change_detector: ChangeDetector,
    ) -> None:
        self._hass = hass
        self._api = api
        self._change_detector = change_detector
        self._desired_temp: float | None = None
        self._enabled = False

    @property
    def desired_temp(self) -> float | None:
        return self._desired_temp

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_desired_temp(self, temp: float) -> None:
        """Set the temperature that should be maintained."""
        self._desired_temp = temp
        self._enabled = True
        _LOGGER.info("Heating Guardian: desired temp set to %s", temp)

    def disable(self) -> None:
        self._enabled = False
        self._desired_temp = None
        _LOGGER.info("Heating Guardian: disabled")

    async def check_and_revert(self, edit_params: dict[str, Any]) -> bool:
        """Check if Heating temp has drifted and revert if so.

        Returns True if a revert was performed.
        """
        if not self._enabled or self._desired_temp is None:
            return False

        data = edit_params.get("data", {})
        param = data.get(GUARDIAN_INDEX, {})
        current_value = param.get("value") if isinstance(param, dict) else None

        if current_value is None:
            _LOGGER.debug("Guardian: cannot read current Heating temp")
            return False

        if abs(float(current_value) - self._desired_temp) < 0.05:
            return False

        _LOGGER.warning(
            "Guardian: Heating temp is %s, desired is %s. Reverting.",
            current_value, self._desired_temp,
        )

        self._change_detector.mark_self_write(GUARDIAN_PARAM)
        success = await self._api.set_param_by_index(
            GUARDIAN_INDEX, self._desired_temp
        )

        if success:
            _LOGGER.info("Guardian: successfully reverted Heating to %s", self._desired_temp)
            self._hass.components.persistent_notification.async_create(
                message=(
                    f"Heating temperature was changed to {current_value}°C. "
                    f"Guardian reverted it to {self._desired_temp}°C."
                ),
                title="EcoNet Grant - Guardian Revert",
                notification_id=f"{DOMAIN}_guardian_revert",
            )
            # Log the guardian revert to the database
            for entry_data in self._hass.data.get(DOMAIN, {}).values():
                if SERVICE_DATABASE in entry_data:
                    db = entry_data[SERVICE_DATABASE]
                    self._hass.async_create_task(
                        db.async_log_change(
                            self._hass,
                            {
                                "name": GUARDIAN_PARAM,
                                "index": GUARDIAN_INDEX,
                                "old_value": current_value,
                                "new_value": self._desired_temp,
                            },
                            source="guardian",
                        )
                    )
                    break
        else:
            _LOGGER.error("Guardian: FAILED to revert Heating")
            self._change_detector.clear_self_write(GUARDIAN_PARAM)

        return success
