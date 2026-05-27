import argparse
import logging
import socket
import threading
import time

import pyvisa
from pyvisa import VisaIOError
from pyvisa.resources import MessageBasedResource

from tekafp import __version__
from tekafp.api_server import (
    RawPacket,
    get_raw_packet,
    run_api_server,
    send_packet_data,
    startup_event,
)
from tekafp.api_server.error import APIError
from tekafp.api_server.packets import (
    ErrorPacketData,
    HandshakePacketData,
    MacroAction,
    MacroActionPacketData,
    PacketData,
    ScopeActionPacketData,
    ScopeInfoPacketData,
    ScopeListPacketData,
)
from tekafp.input import Input
from tekafp.scope.controller import Controller
from tekafp.scope.macros import MacroManager
from tekafp.uart import MockUARTBridge, UARTBridge


logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/ttyAMA0"
DEFAULT_VISA_BACKEND = "@py"
DEFAULT_VISA_TIMEOUT = 5000
DEFAULT_BAUDRATE = 115200


def _start_api() -> None:
    logger.info("Starting WebSocket API thread...")
    api_thead = threading.Thread(target=run_api_server, daemon=True)
    api_thead.start()
    startup_event.wait()


class TekAfp:
    def __init__(self) -> None:
        self._uart_port: str = DEFAULT_PORT
        self._mock: bool = False
        self._verbose: bool = False
        self._auto_connect: bool = False
        self.bridge: UARTBridge = None
        self._rm = pyvisa.ResourceManager(DEFAULT_VISA_BACKEND)
        self.scopes: dict[str, Controller] = {}
        self.macro_manager: MacroManager = None
        self._hostname: str = socket.gethostname()

    def _parse_args(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("-m", "--mock", action="store_true", help="Run in mock mode")
        parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
        parser.add_argument(
            "-a",
            "--auto",
            action="store_true",
            help="Automatically connect to the first available scope",
        )
        parser.add_argument(
            "-p", "--port", type=str, default=DEFAULT_PORT, help="UART port to connect to"
        )
        args = parser.parse_args()
        self._mock = args.mock
        self._verbose = args.verbose
        self._auto_connect = args.auto

    def setup(self) -> None:
        self._parse_args()
        log_level = logging.DEBUG if self._verbose else logging.INFO
        logging.basicConfig()
        logging.getLogger("tekafp").setLevel(log_level)
        self.bridge = self.connect_uart(self._uart_port, self._mock)
        _start_api()
        self.macro_manager = MacroManager()

        if self._auto_connect:
            self.auto_connect()

    def run(self) -> None:
        try:
            last_sync = time.monotonic()
            last_input = 0.0  # no input yet
            sync_period_s = 0.05

            while True:
                raw = self.bridge.get()
                if not self._mock and self.scopes and raw:
                    try:
                        inp = Input.from_bytes(raw)
                    except (ValueError, IndexError) as e:
                        logger.error(f"Bad UART message {raw!r}: {e}")
                        continue

                    # iterating all scopes here would allow control of multiple at once
                    ctrl = list(self.scopes.values())[0]
                    if self.macro_manager.should_handle(inp):
                        self.macro_manager.handle_uart_input(raw, inp, ctrl)
                    else:
                        ctrl.handle_input(inp)
                    last_input = time.monotonic()

                new_packet = get_raw_packet()
                if new_packet:
                    self._handle_packet(new_packet)

                now = time.monotonic()
                if (
                    not self._mock
                    and self.scopes
                    and now - last_sync > sync_period_s
                    and now - last_input > 0.05
                ):
                    ctrl = list(self.scopes.values())[0]
                    ctrl.sync_all_changed_channels_from_scope()
                    ctrl.sync_selected_source_from_scope()
                    ctrl.sync_fast_acquire_from_scope()
                    ctrl.sync_run_stop_from_scope()
                    ctrl.sync_trigger_state()
                    ctrl.sync_zoom()
                    ctrl.sync_touch_off()
                    ctrl.sync_high_res()
                    last_sync = now

        except KeyboardInterrupt:
            logger.info("\nTEK AFP stopping...\n")
        finally:
            logger.info("Closing connections...")
            for ctrl in self.scopes.values():
                if ctrl:
                    ctrl.res.close()
            self.send_scope_connection_led(False)
            self.bridge.close()

    @staticmethod
    def connect_uart(port: str, mock: bool = False) -> UARTBridge:
        if mock:
            return MockUARTBridge(port, baudrate=DEFAULT_BAUDRATE, timeout=1, write_timeout=1)
        bridge = UARTBridge(port, baudrate=DEFAULT_BAUDRATE, timeout=0.1, write_timeout=1)
        if not bridge.connect():
            raise RuntimeError(f"Failed to open UART on {port}")
        logger.info(f"Connected UART: {port} @ {DEFAULT_BAUDRATE}")
        return bridge

    def connect_to_scope(self, resource_name: str) -> None:
        try:
            scope: MessageBasedResource = self._rm.open_resource(
                resource_name,
                resource_pyclass=MessageBasedResource,
                timeout=DEFAULT_VISA_TIMEOUT,
                write_termination="\n",
                read_termination="\n",
            )
        except (VisaIOError, ValueError) as err:
            send_packet_data(
                ErrorPacketData(resource_name, APIError.CONNECTION_ERROR, error_str=str(err))
            )
            return

        ctrl = Controller(scope, self.bridge)
        ctrl.sync_all_channels_from_scope()
        self.scopes[resource_name] = ctrl
        self.send_scope_connection_led(True)
        send_packet_data(
            ScopeInfoPacketData(
                resource_name=resource_name, idn=ctrl.idn, channel_count=ctrl.channel_count
            )
        )

    def _handle_packet(self, packet: RawPacket) -> None:
        for pd in packet["data"]:
            data = PacketData.decode(pd)
            match data:
                case HandshakePacketData(client_id, client_version):
                    logger.info(f"client {client_id} {client_version} connected")
                    send_packet_data(HandshakePacketData(self._hostname, __version__))
                case ScopeActionPacketData(action=a):
                    logger.debug(f"Received packet action='{a}'")
                    match a:
                        case "enable":
                            if data.resource_name not in self.scopes:
                                logger.info(f"enabling scope {data.resource_name}")
                                if self._mock:
                                    self.scopes[data.resource_name] = None
                                    send_packet_data(
                                        ScopeInfoPacketData(
                                            data.resource_name,
                                            "TEKTRONIX,MSO58,C012345,CF:91.1CT FV:1.0.1.8",
                                            8,
                                        )
                                    )
                                else:
                                    self.connect_to_scope(data.resource_name)
                        case "disable":
                            if data.resource_name in self.scopes:
                                logger.info(f"disabling scope {data.resource_name}")
                                if self._mock:
                                    del self.scopes[data.resource_name]
                                else:
                                    c = self.scopes.pop(data.resource_name)
                                    c.res.close()

                                    if not self.scopes:
                                        self.send_scope_connection_led(False)
                        case "list":
                            if self._mock:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            "USB0::0x0699::0x0363::C102912::INSTR": False,
                                            "USB0::0x0699::0x0408::B011823::INSTR": False,
                                        }
                                    )
                                )
                            else:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            r: r in self.scopes
                                            for r in self._rm.list_resources(
                                                "(USB?*::INSTR|TCPIP?*::INSTR)"
                                            )
                                        }
                                    )
                                )
                        case _:
                            logger.error(f"Unknown action: {a}")
                case MacroActionPacketData(action=a, slot=slot):
                    if a == MacroAction.RECORD:
                        self.macro_manager.start_recording(slot)
                    elif a == MacroAction.SAVE:
                        self.macro_manager.stop_recording(slot)
                    elif a == MacroAction.DELETE:
                        self.macro_manager.delete_macro(slot)
                    else:
                        logger.error("Unknown macro action: %s", a)
                case _:
                    logger.error(f"Unknown or incorrect packet type {data.type}")

    def send_scope_connection_led(self, state: bool) -> None:
        msg = f"ISP_CON:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def auto_connect(self) -> None:
        resources = self._rm.list_resources("(USB?*::INSTR|TCPIP?*::INSTR)")

        if not resources:
            logger.info("No scopes found")
        else:
            first = resources[0]
            logger.info(f"Connecting to: {first}")
            if first not in self.scopes:
                self.connect_to_scope(first)
