import logging
import time
from typing import Callable, Optional

from tekafp.api_server import send_packet_data
from tekafp.api_server.packets import MacroStatePacketData
from tekafp.input import Input


logger = logging.getLogger(__name__)


class MacroManager:
    NUM_SLOTS = 4

    PHYSICAL_MACRO_IDS = {"M10": 0, "M20": 1, "M30": 2, "M40": 3}

    def __init__(self, on_input: Callable[[Input], None]) -> None:
        self.macros: dict[int, list[Input]] = {}
        self.recording_slot: Optional[int] = None
        self._on_input = on_input
        self._record_buf: list[Input] = []

    def _valid_slot(self, slot: int) -> bool:
        return 0 <= slot < self.NUM_SLOTS

    def send_macro_state(self) -> None:
        send_packet_data(MacroStatePacketData([bool(macro) for macro in self.macros]))

    def start_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return

        if self.recording_slot is not None and self.recording_slot != slot:
            logger.debug(f"Stopping slot {self.recording_slot} before recording slot {slot}")

        self.recording_slot = slot
        self.macros[slot] = []
        logger.debug(f"Recording started for slot {slot}")

    def stop_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            logger.debug(f"Invalid slot {slot}")
            return

        if self.recording_slot != slot:
            return

        self.recording_slot = None
        logger.debug(f"Recording stopped for slot {slot}. {len(self.macros[slot])} events saved.")
        self.send_macro_state()

    def delete_macro(self, slot: int) -> None:
        self.macros.pop(slot, None)
        self.send_macro_state()

    def handle_input(self, inp: Input) -> None:
        """Called for every input and only records if active"""
        if self.recording_slot is not None:
            self._record_buf.append(inp)
        self._on_input(inp)

    def playback(self, slot: int) -> None:
        for inp in self.macros.get(slot, []):
            self._on_input(inp)
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return
