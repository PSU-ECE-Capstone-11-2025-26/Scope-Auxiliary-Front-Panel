import json
import logging
from pathlib import Path
from typing import Iterable

from tekafp.api_server import send_packet_data
from tekafp.api_server.packets import MacroStatePacketData

from .commands import Command
from .scope import Scope


logger = logging.getLogger(__name__)


class MacroManager:
    NUM_SLOTS = 4
    PHYSICAL_MACRO_IDS = {"M10": 0, "M20": 1, "M30": 2, "M40": 3}

    def __init__(self, data_path: Path | None = None) -> None:
        self.macros: dict[int, list[Command]] = {}
        self.recording_slot: int | None = None
        self._record_buf: list[Command] = []
        self._path = data_path
        if data_path is not None:
            self._path /= "macros.json"
            self._load()

    def _valid_slot(self, slot: int) -> bool:
        return 0 <= slot < self.NUM_SLOTS

    def send_macro_state(self) -> None:
        send_packet_data(
            MacroStatePacketData([slot in self.macros for slot in range(self.NUM_SLOTS)])
        )

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {str(slot): [cmd.to_dict() for cmd in steps] for slot, steps in self.macros.items()}
        self._path.write_text(json.dumps(data, indent=2))
        logger.debug("Saved macros to %s", self._path)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self.macros = {
                int(slot): [Command.from_dict(d) for d in steps] for slot, steps in data.items()
            }
            logger.info("Loaded %d macro(s) from %s", len(self.macros), self._path)
        except Exception as e:
            logger.error("Failed to load macros from %s: %s", self._path, e)

    def start_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return

        if self.recording_slot is not None and self.recording_slot != slot:
            logger.debug(f"Stopping slot {self.recording_slot} before recording slot {slot}")
            self.macros[self.recording_slot] = self._record_buf
            self._save()

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
        self._save()
        self.send_macro_state()

    def delete_macro(self, slot: int) -> None:
        self.macros.pop(slot, None)
        self._save()
        self.send_macro_state()

    def handle_input(self, cmd: Command) -> None:
        if self.recording_slot is not None:
            self._record_buf.append(cmd)

    def playback(self, slot: int, scopes: Iterable[Scope]) -> None:
        if not self._valid_slot(slot):
            logger.error(f"Invalid slot {slot}")
            return
        if self.recording_slot is not None:
            logger.warning("Cannot play while recording")
            return
        connected = [s for s in scopes if s.connected.value]
        for cmd in self.macros.get(slot, []):
            for scope in connected:
                try:
                    cmd.execute(scope)
                except Exception as e:
                    logger.error("Playback failed, cmd=%s: %s", cmd.kind, e)
