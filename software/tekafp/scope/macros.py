import logging
import time
from typing import Optional

from tekafp.api_server import send_packet_data
from tekafp.api_server.packets import MacroStatePacketData
from tekafp.input import Input
from tekafp.scope.controller import Controller


logger = logging.getLogger(__name__)


class MacroManager:
    NUM_SLOTS = 4

    PHYSICAL_MACRO_IDS = {"M10": 0, "M20": 1, "M30": 2, "M40": 3}

    def __init__(self) -> None:
        self.macros: list[list[bytes | tuple[str, int, bool]]] = [[] for _ in range(self.NUM_SLOTS)]
        self.recording_slot: Optional[int] = None
        self._playing_back = False

    def _valid_slot(self, slot: int) -> bool:
        return 0 <= slot < self.NUM_SLOTS

    def should_handle(self, inp: Input) -> bool:
        msg_id = str(inp.id)

        return self.recording_slot is not None or msg_id in self.PHYSICAL_MACRO_IDS

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

    def handle_uart_input(self, raw: bytes, inp: Input, ctrl: Controller) -> None:
        msg_id = str(inp.id)

        if msg_id in self.PHYSICAL_MACRO_IDS:
            try:
                if int(inp.value) != 1:
                    return
            except ValueError:
                return

            slot = self.PHYSICAL_MACRO_IDS[msg_id]
            self.playback(slot, ctrl)
            return

        is_channel_toggle = msg_id in ("V10", "V20", "V30", "V40", "V50", "V60", "V70", "V80")

        if self.recording_slot is not None and not self._playing_back and is_channel_toggle:
            ch = int(msg_id[1])

            ctrl.handle_input(inp)

            desired = ctrl._channels[ch]
            event = ("channel_state", ch, desired)

            self.macros[self.recording_slot].append(event)
            logger.debug(f"slot {self.recording_slot} + {event!r}")
            return

        if self.recording_slot is not None and not self._playing_back:
            self.macros[self.recording_slot].append(raw)
            logger.debug(f"slot {self.recording_slot} + {raw!r}")

        ctrl.handle_input(inp)

    def playback(self, slot: int, ctrl: Controller) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return

        if self.recording_slot is not None:
            return

        macro = self.macros[slot]
        if not macro:
            return

        played_channel_event = False

        self._playing_back = True

        try:
            for raw in macro:
                if isinstance(raw, tuple):
                    kind, ch, desired = raw

                    if kind == "channel_state":
                        played_channel_event = True
                        ctrl.force_channel_display(ch, desired)
                        time.sleep(0.25)
                        continue

                try:
                    inp = Input.from_bytes(raw)
                except (IndexError, ValueError) as e:
                    logger.exception(f"Bad recorded message {raw!r}: {e}")
                    continue

                if str(inp.id) in self.PHYSICAL_MACRO_IDS:
                    continue

                ctrl.handle_input(inp)
                time.sleep(0.25)
            if played_channel_event:
                ctrl._source_channel = max((k for k, v in ctrl._channels.items() if v), default=0)

                ctrl.set_scope_selected_source()
                ctrl.send_selected_channel_leds()

        finally:
            self._playing_back = False
            logger.debug(f"Playback done for slot {slot}")
