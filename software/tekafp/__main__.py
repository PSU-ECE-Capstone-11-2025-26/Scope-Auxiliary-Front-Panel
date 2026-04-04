import threading

import pyvisa
from pyvisa.resources import MessageBasedResource

from tekafp.api_server import (
    RawPacket,
    get_raw_packet,
    run_api_server,
    send_packet_data,
    startup_event,
)
from tekafp.api_server.packets import (
    MacroRecordPacketData,
    PacketData,
    ScopeActionPacketData,
    ScopeListPacketData,
)
from tekafp.input import Input
from tekafp.uart import UARTBridge
from tekafp.util import clamp, parse_resp


# UART config
PORT = "/dev/serial0"
BAUD = 115200

# Scope config
PYVISA_BACKEND = "@py"
SCOPE_TIMEOUT_MS = 5000

# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10  # Vertical position step per encoder detent (+/-1)
HORIZ_STEP_PCT = 1.0  # Horizontal position step in percent (0..~100) per detent


def connect_uart() -> UARTBridge:
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        self.scope: MessageBasedResource = scope

        self._channels: dict[int, bool] = {ch: False for ch in range(1, 9)}
        self._source_channel: int = 0

    def set_channel_display(self, channel: int) -> None:
        if channel not in range(1, 9):
            return
        last_state: bool = self._channels[channel]

        if self._source_channel == channel:
            # enabled and source => disable, select highest enabled as active
            self._channels[channel] = False
            highest: int = 0
            for k, v in self._channels.items():
                if v:
                    highest = k
                    if k > channel:
                        break
            self._source_channel = highest
        elif last_state:
            # enabled => set as source
            self._source_channel = channel
        else:
            # disabled => enable, set as source
            self._channels[channel] = True
            self._source_channel = channel

        if self._source_channel == 0:
            self.scope.write("DISPLAY:SELECT:SOURCE:NONE")
        else:
            self.scope.write(f"DISPLAY:SELECT:SOURCE:CH{self._source_channel}")

        if last_state != self._channels[channel]:
            self.scope.write(
                f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self._channels[channel])}"
            )

        print(
            f"[SCOPE] CH{channel} display -> {self._channels[channel]} (source={self._source_channel})"  # noqa: E501
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"CH{ch}:POSITION {new}")
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.write(f"HORIZONTAL:POSITION {new}")
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    def encoder_trigger_level(self, detents: int) -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        ab = "A"
        source: str = parse_resp(self.scope.query(f"TRIGGER:{ab}:EDGE:SOURCE?"), str)
        query = f"TRIGGER:{ab}:LEVEL:CH{source}"
        cur: float = parse_resp(self.scope.query(query + "?"), float)

        trigger_scale: float = 0.4
        new = cur + detents * trigger_scale
        new = clamp(new, -100.0, 100.0)

        self.scope.write(query + f" {new}")
        print(f"[SCOPE] trigger level (%): {cur:.2f} -> {new:.2f}")

    def next_trigger_slope(self) -> None:
        cur: str = parse_resp(self.scope.query("TRIGGER:A:EDGE:SLOPE?"), str).upper()
        new: str = ""
        match cur:
            case "RISE":
                new = "FALL"
            case "FALL":
                new = "EITHER"
            case "EITHER":
                new = "RISE"
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        self.scope.write(f"TRIGGER:A:EDGE:SLOPE {new}")

    # Toggle the scope's Run/Stop state
    def toggle_run_stop(self) -> None:
        resp = self.scope.query("ACQUIRE:STATE?").strip().upper()

        # Tek scopes may return RUN/STOP, ON/OFF, or 1/0
        if resp in ("RUN", "ON", "1"):
            self.scope.write("ACQUIRE:STATE STOP")
            print("[SCOPE] Run/Stop -> STOP")
            return
        else:
            self.scope.write("ACQUIRE:STATE RUN")
            print("[SCOPE] Run/Stop -> RUN")
            return

    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.write("AUTOSET EXECUTE")
        print("[SCOPE] AutoSet executed")

    # Toggle the scope's Fast Acquire state
    def toggle_fast_acquire(self) -> None:
        resp = self.scope.query("FASTACQ:STATE?").strip().upper()

        # Tek scopes may return headers, e.g. ":FASTACQ:STATE 1"
        if resp.endswith("1") or resp.endswith("ON"):
            self.scope.write("FASTACQ:STATE OFF")
            print("[SCOPE] Fast Acquire -> OFF")
            return
        else:
            self.scope.write("FASTACQ:STATE ON")
            print("[SCOPE] Fast Acquire -> ON")
            return

    # UART event handler
    def handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V80, KA1/KA0, KB1/KB0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        # Channel Selection
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60", "V70", "V80"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V60' -> 6
            self.set_channel_display(ch)
            return

        # Encoder 1 rotation => vertical position of current active channel
        if msg_id == "KA1":
            detents = int(val)  # should be +1 / -1
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder 2 rotation => horizontal position (global)
        if msg_id == "KB1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return

        # trigger level encoder
        if msg_id == "TL1":
            detents = int(val)
            if detents:
                self.encoder_trigger_level(detents)
            return
        # trigger level push
        if msg_id == "TL0":
            self.scope.write("TRIGGER:A: SETLevel")
            return

        # trigger force
        if msg_id == "TF0":
            self.scope.write("TRIGGER FORCE")
            return

        # trigger slope type
        if msg_id == "TS0":
            self.next_trigger_slope()
            return

        # trigger mode
        if msg_id == "TM0":
            cur: str = parse_resp(self.scope.query("TRIGGER:A:MODE?"), str).upper()
            new: str = "AUTO" if cur == "NORMAL" else "NORMAL"
            self.scope.write(f"TRIGGER:A:MODE {new}")
            return

        # Run/Stop button
        if msg_id == "AR0":
            self.toggle_run_stop()
            return

        # Fast Acquire button
        if msg_id == "AF0":
            self.toggle_fast_acquire()
            return

        # AutoSet button
        if msg_id == "XA0":
            self.autoset()
            return

def main() -> None:
    # internal setup
    bridge = connect_uart()
    print("Starting WebSocket API thread...")
    api_thead = threading.Thread(target=run_api_server, daemon=True)
    api_thead.start()
    startup_event.wait()

    # ctrl setup
    rm: pyvisa.ResourceManager = pyvisa.ResourceManager()
    scopes: dict[str, Controller] = {}

    def connect_to_scope(idn: str) -> None:
        scope: MessageBasedResource = rm.open_resource(
            idn,
            resource_pyclass=MessageBasedResource,
            timeout=SCOPE_TIMEOUT_MS,
            write_termination="\n",
            read_termination="\n",
        )
        # Make sure we're in a mode where horizontal position behaves like the
        # front panel knob
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        scope.write("HORIZONTAL:DELAY:MODE OFF")
        print("Connected ctrl:", scope.query("*IDN?").strip())
        scopes[idn] = Controller(scope)

    def handle_packet(packet: RawPacket) -> None:
        for pd in packet["data"]:
            data = PacketData.decode(pd)
            match data:
                case ScopeActionPacketData(action=a):
                    match a:
                        case "enable":
                            if data.scope not in scopes:
                                connect_to_scope(data.scope)
                        case "disable":
                            if data.scope in scopes:
                                c = scopes.pop(data.scope)
                                c.scope.close()
                        case "list":
                            send_packet_data(
                                ScopeListPacketData(
                                    rm.list_resources("(USB?*::INSTR|TCPIP?*::INSTR)")
                                )
                            )
                        case _:
                            print(f"Unknown action: {a}")
                case MacroRecordPacketData():
                    if data.record:
                        pass
                        # TODO record for slot data.slot
                        # If a different slot is recording, stop that one first.
                    else:
                        pass  # TODO stop recording for slot data.slot
                case _:
                    print(f"Unknown or incorrect packet type {data.type}")

    try:
        while True:
            raw = bridge.get()
            if scopes and raw:
                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"Bad UART message {raw!r}: {e}")
                    continue
                # TODO: iterate all scopes instead to control multiple at once
                list(scopes.values())[0].handle_input(inp)
            new_packet = get_raw_packet()
            if new_packet:
                handle_packet(new_packet)

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        for ctrl in scopes.values():
            ctrl.scope.close()
        bridge.close()


if __name__ == "__main__":
    main()
