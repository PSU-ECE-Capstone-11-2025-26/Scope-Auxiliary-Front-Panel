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
from tekafp.scope.scope import Scope
from tekafp.scope.state import TriggerMode, TriggerEdgeSlope, TriggerState
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
        self.synched_scope: str = None
        self.macro_manager: MacroManager = None
        self._hostname: str = socket.gethostname()
        self._led_tokens = []

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

    def _synch_worker(self) -> None:
        last_sync = time.monotonic()
        last_input = 0.0  # no input yet
        sync_period_s = 0.05

        while True:
            for ctrl in self.scopes.values():
                ctrl.scope
        now = time.monotonic()
        if (
            not self._mock
            and self.scopes
            and now - last_sync > sync_period_s
            and now - last_input > 0.05
        ):
            ctrl = list(self.scopes.values())[0]
            ctrl.sync_selected_source_from_scope()
            ctrl.sync_fast_acquire_from_scope()
            ctrl.sync_run_stop_from_scope()
            ctrl.sync_trigger_state()
            ctrl.sync_zoom()
            last_sync = now

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

    def set_synched_scope(self, resource_name: str) -> None:
        if self.synched_scope is not None:
            self._register_led_callbacks(self.scopes[self.synched_scope])
        self.synched_scope = resource_name
        self._register_led_callbacks(self.scopes[self.synched_scope])
        # TODO: force sync
        #  read current .value of each and write LED state

    def _register_led_callbacks(self, scope: Scope) -> None:
        self._led_tokens = [
            scope.connected.register(
                lambda _, v: self.bridge.queue_write(f"ISP_CON:{int(v)}\n".encode())
            ),
            scope.source_channel.register(
                lambda _, v: self.bridge.queue_write(f"IVP1:{int(v)}\n".encode())
            ),
            scope.run.register(lambda _, v: self.bridge.queue_write(f"IAF0:{int(v)}\n".encode())),
            scope.trigger_source.register(
                lambda _, v: self.bridge.queue_write(f"ITL1:{v.number}\n".encode())
            ),
            scope.trigger_mode.register(self._cb_trigger_mode),
            scope.trigger_edge_slope.register(self._cb_trigger_slope),
            scope.trigger_state.register(self._cb_trigger_state),
            scope.zoom.register(lambda _, v: self.bridge.queue_write(f"IHZ0:{int(v)}\n".encode())),
            scope.fast_acquire.register(
                lambda _, v: self.bridge.queue_write(f"IAF0:{int(v)}\n".encode())
            ),
        ]

    def _unregister_led_callbacks(self, scope: Scope) -> None:
        scope.connected.clear_callbacks()
        scope.source_channel.clear_callbacks()
        scope.run.clear_callbacks()
        scope.trigger_source.clear_callbacks()
        scope.trigger_mode.clear_callbacks()
        scope.trigger_edge_slope.clear_callbacks()
        scope.trigger_state.clear_callbacks()
        scope.zoom.clear_callbacks()
        scope.fast_acquire.clear_callbacks()
        self._led_tokens = []

    def _cb_trigger_state(self, _: TriggerState, state: TriggerState) -> None:
        match state:
            case "READY" | "AUTO":
                ready = 1
                trig = 0
            case "TRIGGER":
                ready = 0
                trig = 1
            case _:
                ready = trig = 0
        self.bridge.write_sync(f"ITF0_R:{ready}\n".encode())
        self.bridge.write_sync(f"ITF0_T:{trig}\n".encode())

    def _cb_trigger_slope(self, _: TriggerEdgeSlope, slope: TriggerEdgeSlope) -> None:
        match slope:
            case "RISE":
                rise = 1
                fall = 0
            case "FALL":
                rise = 0
                fall = 1
            case "EITHER":
                rise = fall = 1
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        self.bridge.queue_write(f"ITS0_UP:{rise}\n".encode())
        self.bridge.queue_write(f"ITS0_DN:{fall}\n".encode())

    def _cb_trigger_mode(self, _: TriggerMode, mode: TriggerMode) -> None:
        a = mode == TriggerMode.AUTO
        self.bridge.queue_write(f"ITM0_A:{int(a)}\n".encode())
        self.bridge.queue_write(f"ITM0_N:{int(not a)}\n".encode())

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
