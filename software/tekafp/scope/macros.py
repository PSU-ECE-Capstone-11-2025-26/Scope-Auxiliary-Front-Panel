from dataclasses import asdict, dataclass
import logging
from typing import Callable, Iterable

from tekafp.api_server import send_packet_data
from tekafp.api_server.packets import MacroStatePacketData

from .actions import Action
from .scope import Scope
from .state import Channel, TriggerEdgeSlope, TriggerMode


logger = logging.getLogger(__name__)


@dataclass
class MacroStep:
    type: str
    # stateful controls
    channel: str | None = None
    enabled: bool | None = None
    mode: str | None = None
    # encoder
    detents: int | None = None
    # vertical fine only
    fine: bool | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "MacroStep":
        return cls(**data)


class MacroManager:
    NUM_SLOTS = 4

    PHYSICAL_MACRO_IDS = {"M10": 0, "M20": 1, "M30": 2, "M40": 3}

    def __init__(self) -> None:
        self.macros: dict[int, list[MacroStep]] = {}
        self.recording_slot: int | None = None
        self._record_buf: list[MacroStep] = []

    def _valid_slot(self, slot: int) -> bool:
        return 0 <= slot < self.NUM_SLOTS

    def send_macro_state(self) -> None:
        send_packet_data(
            MacroStatePacketData([slot in self.macros for slot in range(self.NUM_SLOTS)])
        )

    def start_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return

        if self.recording_slot is not None and self.recording_slot != slot:
            logger.debug(f"Stopping slot {self.recording_slot} before recording slot {slot}")
            self.macros[self.recording_slot] = self._record_buf

        self.recording_slot = slot
        self._record_buf = []
        logger.debug(f"Recording started for slot {slot}")

    def stop_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            logger.debug(f"Invalid slot {slot}")
            return

        if self.recording_slot != slot:
            return

        self.recording_slot = None
        self.macros[slot] = self._record_buf
        logger.debug(f"Recording stopped for slot {slot}. {len(self.macros[slot])} events saved.")
        self._record_buf = []
        self.send_macro_state()

    def delete_macro(self, slot: int) -> None:
        self.macros.pop(slot, None)
        self.send_macro_state()

    def handle_input(self, step: MacroStep) -> None:
        """Called for every input and only records if active"""
        if self.recording_slot is not None:
            self._record_buf.append(step)

    def playback(self, slot: int, scopes: Iterable[Scope]) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return
        if self.recording_slot is not None:
            logger.warning("Cannot play while recording")
            return
        connected = [s for s in scopes if s.connected.value]
        for step in self.macros.get(slot, []):
            action = self._step_to_action(step)
            if action:
                for scope in connected:
                    try:
                        action(scope)
                    except Exception as e:
                        logger.error("Playback failed, step %s, %s", step.type, e)
            else:
                logger.error("Unknown step type %s", step.type)
        for scope in connected:
            # if channels have changed we want to make sure the source state is ok
            Action.sync_all_channels(scope)

    @staticmethod
    def _step_to_action(step: MacroStep) -> Callable[[Scope], None] | None:
        match step.type:
            # stateful
            case "set_channel":
                ch = Channel.from_label(step.channel)
                return lambda scope, c=ch, e=step.enabled: Action.set_channel(scope, c, e)
            case "set_run_stop":
                return lambda scope, s=step.enabled: Action.set_run_stop(scope, s)
            case "set_fast_acquire":
                return lambda scope, e=step.enabled: Action.set_fast_acquire(scope, e)
            case "set_zoom":
                return lambda scope, e=step.enabled: Action.set_zoom(scope, e)
            case "set_trigger_slope":
                return lambda scope, m=step.mode: Action.set_trigger_slope(
                    scope, TriggerEdgeSlope(m)
                )
            case "set_trigger_mode":
                return lambda scope, m=step.mode: Action.set_trigger_mode(scope, TriggerMode(m))
            # encoders
            case "adjust_vertical_position":
                return lambda scope, d=step.detents: Action.adjust_vertical_position(scope, d)
            case "adjust_vertical_scale":
                return lambda scope, d=step.detents, f=step.fine: Action.adjust_vertical_scale(
                    scope, d, f or False
                )
            case "adjust_horizontal_position":
                return lambda scope, d=step.detents: Action.adjust_horizontal_position(scope, d)
            case "adjust_horizontal_scale":
                return lambda scope, d=step.detents: Action.adjust_horizontal_scale(scope, d)
            case "adjust_trigger_level":
                return lambda scope, d=step.detents: Action.adjust_trigger_level(scope, d)
            case "adjust_zoom_scale":
                return lambda scope, d=step.detents: Action.adjust_zoom_scale(scope, d)
            case "adjust_pan":
                return lambda scope, d=step.detents: Action.adjust_pan(scope, d)
            # stateless
            case "center_vertical_position":
                return Action.center_vertical_position
            case "center_horizontal_position":
                return Action.center_horizontal_position
            case "center_trigger":
                return Action.center_trigger
            case "force_trigger":
                return Action.force_trigger
            case "run_autoset":
                return Action.run_autoset
            case "set_touch_enabled":
                return Action.set_touch_enabled
            case "set_acquire_state":
                return lambda scope, s=step.mode: Action.set_acquire_mode(scope, s)
            case _:
                return None
