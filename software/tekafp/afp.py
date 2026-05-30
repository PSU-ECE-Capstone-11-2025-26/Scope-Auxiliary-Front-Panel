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
from tekafp.scope.actions import Action
from tekafp.scope.macros import MacroManager, MacroStep
from tekafp.scope.scope import Scope
from tekafp.scope.state import Channel, ChannelState, TriggerEdgeSlope, TriggerMode, TriggerState
from tekafp.uart import MockUARTBridge, UARTBridge
from tekafp.util.observable import ObservableVariable


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
    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_DELAY_S = 2.0
    SYNC_DELAY_S = 0.1
    GP_FINE_SCALE = 20
    GP_COARSE_SCALE = 100

    def __init__(self) -> None:
        self._uart_port: str = DEFAULT_PORT
        self._mock: bool = False
        self._verbose: bool = False
        self._auto_connect: bool = False
        self.bridge: UARTBridge = None
        self._rm = pyvisa.ResourceManager(DEFAULT_VISA_BACKEND)
        self.scopes: dict[str, Scope] = {}
        self.synced_scope: str = None
        self.macro_manager: MacroManager = None
        self._fine_mode: ObservableVariable[bool] = ObservableVariable(False)
        self._gp_a_fine_mode: ObservableVariable[bool] = ObservableVariable(False)
        self._gp_b_fine_mode: ObservableVariable[bool] = ObservableVariable(False)
        self._hostname: str = socket.gethostname()
        self._led_tokens: list[int] = []
        self._channel_led_tokens: dict[Channel, int] = {}

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
        self._fine_mode.register(
            lambda _, v: self._set_led("IVS0", int(self._fine_mode.value))
        )
        self._gp_a_fine_mode.register(
            lambda _, v: self._set_led("IKA0", int(self._gp_a_fine_mode.value))
        )
        self._gp_b_fine_mode.register(
            lambda _, v: self._set_led("IKB0", int(self._gp_b_fine_mode.value))
        )

        if self._auto_connect:
            self.auto_connect()

    def run(self) -> None:
        last_sync = 0.0
        try:
            while True:
                raw = self.bridge.get(timeout=0.01)
                if not self._mock and self.synced_scope and raw:
                    try:
                        inp = Input.from_bytes(raw)
                    except (ValueError, IndexError) as e:
                        logger.error(f"Bad UART message {raw!r}: {e}")
                    else:
                        self._handle_input(inp)

                new_packet = get_raw_packet()
                if new_packet:
                    self._handle_packet(new_packet)

                now = time.monotonic()
                if self.synced_scope and now - last_sync >= self.SYNC_DELAY_S:
                    last_sync = now
                    try:
                        Action.sync(self.scopes[self.synced_scope])
                    except VisaIOError as e:
                        logger.warning("Sync error: %s", e)
                        self._handle_scope_disconnect(self.synced_scope)

        except KeyboardInterrupt:
            logger.info("\nTEK AFP stopping...\n")
        finally:
            logger.info("Closing connections...")
            for scope in self.scopes.values():
                if scope:
                    scope.resource.close()
            self._reset_leds()
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

    def _connect(self, resource_name: str) -> MessageBasedResource:
        resource: MessageBasedResource = self._rm.open_resource(
            resource_name,
            resource_pyclass=MessageBasedResource,
            timeout=DEFAULT_VISA_TIMEOUT,
            write_termination="\n",
            read_termination="\n",
        )
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        resource.write("HORIZONTAL:DELAY:MODE OFF")
        return resource

    def connect_to_scope(self, resource_name: str) -> None:
        try:
            resource = self._connect(resource_name)
        except (VisaIOError, ValueError) as err:
            send_packet_data(
                ErrorPacketData(resource_name, APIError.CONNECTION_ERROR, error_str=str(err))
            )
            return

        scope = Scope.connect(resource)
        self.scopes[resource_name] = scope
        logger.info("Connected ctrl: %s, channels=%d", scope.idn, scope.channel_count)
        scope.connected.value = True
        if self.synced_scope is None:
            self.set_synced_scope(resource_name)
        send_packet_data(
            ScopeInfoPacketData(
                resource_name=resource_name, idn=scope.idn, channel_count=scope.channel_count
            )
        )

    def _handle_scope_disconnect(self, resource_name: str) -> None:
        """Attempt to reconnect to a scope."""
        old = self.scopes.get(resource_name)
        if old is None:
            return

        was_synced = resource_name == self.synced_scope
        if was_synced:
            self._reset_leds()
            self._unregister_led_callbacks(old)
        try:
            old.resource.close()
        except VisaIOError:
            pass

        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            logger.info(
                "Reconnect (attempt %d/%d) %s", attempt, self.MAX_RECONNECT_ATTEMPTS, resource_name
            )
            time.sleep(self.RECONNECT_DELAY_S)
            try:
                resource = self._connect(resource_name)
                scope = Scope.connect(resource)
                self.scopes[resource_name] = scope
                scope.connected.value = True
                if was_synced:
                    self.set_synced_scope(resource_name)
                logger.info("Reconnected to %s", resource_name)
                return
            except (VisaIOError, ValueError) as e:
                logger.warning("Attempt failed: %s", e)

        logger.error("Reconnect attempts failed for %s", resource_name)
        self.scopes.pop(resource_name, None)
        if was_synced:
            self.synced_scope = None
        send_packet_data(
            ErrorPacketData(
                resource_name, APIError.CONNECTION_ERROR, error_str="Scope disconnected"
            )
        )

    def _handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V80, VP1/VP0, HP1/HP0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        if self.synced_scope is None:
            return

        msg_id = str(inp.id)
        val = inp.value
        action = None
        step = None

        match msg_id:
            case "M10" | "M20" | "M30" | "M40":
                slot = MacroManager.PHYSICAL_MACRO_IDS[msg_id]
                # special case: macros are played back directly, this method's logic already
                # handles the rest
                self.macro_manager.playback(slot, self.scopes.values())
                return
            # Channel Selection: 'V10' -> ch 1, 'V80' -> ch 8
            case "V10" | "V20" | "V30" | "V40" | "V50" | "V60" | "V70" | "V80":
                ch = Channel.from_number(int(msg_id[1]))
                action = lambda scope, ch=ch: Action.set_channel_display(scope, ch)
                step = MacroStep(
                    "set_channel",
                    channel=ch.label,
                    enabled=self.scopes[self.synced_scope].source_channel.value != ch,
                )
            case "VM0" | "VB0":
                ch = Channel.MATH if msg_id == "VM0" else Channel.BUS
                action = lambda scope, ch=ch: Action.set_channel_display(scope, ch)
                step = MacroStep(
                    "set_channel",
                    channel=ch.label,
                    enabled=self.scopes[self.synced_scope].source_channel.value != ch,
                )
            case "VP1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_vertical_position(scope, d)
                    step = MacroStep("adjust_vertical_position", detents=detents)
            case "VP0":
                if int(val) == 1:
                    action = Action.center_vertical_position
                    step = MacroStep("center_vertical_position")
            case "HP1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_horizontal_position(scope, d)
                    step = MacroStep("adjust_horizontal_position", detents=detents)
            case "HP0":
                if int(val) == 1:
                    action = Action.center_horizontal_position
                    step = MacroStep("center_horizontal_position")
            case "VS1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_vertical_scale(
                        scope, -d, self._fine_mode.value
                    )
                    step = MacroStep(
                        "adjust_vertical_scale", detents=-detents, fine=self._fine_mode.value
                    )
            case "HS1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_horizontal_scale(scope, -d)
                    step = MacroStep("adjust_horizontal_scale", detents=-detents)
            case "VS0":
                # toggle fine mode for vertical scale encoder
                if int(val) == 1:
                    self._fine_mode.value = not self._fine_mode.value
                    logger.debug(
                        f"Vertical scale fine mode -> {'ON' if self._fine_mode.value else 'OFF'}"
                    )
            case "TL1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_trigger_level(scope, d)
                    step = MacroStep("adjust_trigger_level", detents=detents)
            case "TL0":
                action = Action.center_trigger
                step = MacroStep("center_trigger")
            case "TF0":
                action = Action.force_trigger
                step = MacroStep("force_trigger")
            case "TS0":
                action = Action.cycle_trigger_slope
                step = MacroStep(
                    "set_trigger_slope",
                    mode=~self.scopes[self.synced_scope].trigger_edge_slope.value,
                )
            case "TM0":
                action = Action.cycle_trigger_mode
                step = MacroStep(
                    "set_trigger_mode", mode=~self.scopes[self.synced_scope].trigger_mode.value
                )
            case "AR0":
                action = Action.toggle_run_stop
                step = MacroStep(
                    "set_run_stop", enabled=not self.scopes[self.synced_scope].run.value
                )
            case "AF0":
                action = Action.toggle_fast_acquire
                step = MacroStep(
                    "set_fast_acquire",
                    enabled=not self.scopes[self.synced_scope].fast_acquire.value,
                )
            case "XA0":
                action = Action.run_autoset
                step = MacroStep("run_autoset")
            case "XT0":
                action = Action.toggle_touch_enabled
                step = MacroStep(
                    "set_touch_enabled",
                    enabled=not self.scopes[self.synced_scope].touch_enabled.value,
                )
            case "HZ0":
                action = Action.toggle_zoom
                step = MacroStep("set_zoom", enabled=not self.scopes[self.synced_scope].zoom.value)
            case "HZ1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_zoom_scale(scope, d)
                    step = MacroStep("adjust_zoom_scale", detents=detents)
            case "HX1":
                if detents := int(val):
                    action = lambda scope, d=detents: Action.adjust_pan(scope, d)
                    step = MacroStep("adjust_pan", detents=detents)
            case "AH0":
                if int(val) == 1:
                    action = Action.toggle_high_res
                    step = MacroStep(
                        "set_acquire_state",
                        mode="SAMPLE" if self.scopes[self.synced_scope].high_res.value else "HIRES",
                    )
            case "HL0":
                action = lambda scope, d="PREV": Action.navigate(scope, d)
                step = MacroStep("navigate", mode="PREV")
            case "HR0":
                action = lambda scope, d="NEXT": Action.navigate(scope, d)
                step = MacroStep("navigate", mode="NEXT")
            case "KA0":
                self._gp_a_fine_mode.value = not self._gp_a_fine_mode.value
            case "KA1":
                mult = self.GP_FINE_SCALE if self._gp_a_fine_mode.value else self.GP_COARSE_SCALE
                detents = mult * int(val)
                action = lambda scope, what="GPKNOB1", d=detents: Action.fpanel_turn(scope, what, d)
                step = MacroStep("fpanel_turn", mode="GPKNOB1", detents=detents)
            case "KB0":
                self._gp_b_fine_mode.value = not self._gp_b_fine_mode.value
            case "KB1":
                mult = self.GP_FINE_SCALE if self._gp_b_fine_mode.value else self.GP_COARSE_SCALE
                detents = mult * int(val)
                action = lambda scope, what="GPKNOB2", d=detents: Action.fpanel_turn(scope, what, d)
                step = MacroStep("fpanel_turn", mode="GPKNOB2", detents=detents)

        if action:
            for scope in self.scopes.values():
                if scope.connected.value:
                    try:
                        action(scope)
                    except VisaIOError as e:
                        logger.warning("Action failed: on %s: %s", scope.resource_name, e)
        if step:
            self.macro_manager.handle_input(step)

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
                                    if data.resource_name == self.synced_scope:
                                        self.synced_scope = None
                                        self._unregister_led_callbacks(c)
                                        self._reset_leds()
                                    c.resource.close()
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

    def set_synced_scope(self, resource_name: str) -> None:
        if self.synced_scope is not None:
            self._reset_leds()
            self._unregister_led_callbacks(self.scopes[self.synced_scope])
        self.synced_scope = resource_name
        self._register_led_callbacks(self.scopes[self.synced_scope])
        self._force_leds(self.scopes[self.synced_scope])

    def _register_led_callbacks(self, scope: Scope) -> None:
        self._led_tokens = [
            scope.connected.register(lambda _, v: self._set_led("ISP_CON", int(v))),
            scope.source_channel.register(self._cb_source_channel),
            scope.run.register(lambda _, v: self._set_led("IAR0", int(v))),
            # note that for MATH or BUS number is None, so this would send ITL:None. However,
            # in practice the trigger should always be a numbered channel
            scope.trigger_source.register(
                lambda _, v: self._set_led(
                    f"ITL1_C{1 if v == Channel.NONE else v.number}", 0 if v == Channel.NONE else 1
                )
            ),
            scope.trigger_mode.register(self._cb_trigger_mode),
            scope.trigger_edge_slope.register(self._cb_trigger_slope),
            scope.trigger_state.register(self._cb_trigger_state),
            scope.zoom.register(lambda _, v: self._set_led("IHZ0", int(v))),
            scope.fast_acquire.register(lambda _, v: self._set_led("IAF0", int(v))),
            scope.touch_enabled.register(lambda _, v: self._set_led("IT_OFF", int(not v))),
            scope.high_res.register(lambda _, v: self._set_led("IAH0", int(v))),
        ]
        self._channel_led_tokens = {
            ch: obs.register(lambda _, v, ch=ch: self._cb_channel(ch, v))
            for ch, obs in scope.channels.items()
        }

    def _unregister_led_callbacks(self, scope: Scope) -> None:
        tokens_per_var = [
            scope.connected,
            scope.source_channel,
            scope.run,
            scope.trigger_source,
            scope.trigger_mode,
            scope.trigger_edge_slope,
            scope.trigger_state,
            scope.zoom,
            scope.fast_acquire,
            scope.touch_enabled,
            scope.high_res,
        ]
        for var, token in zip(tokens_per_var, self._led_tokens, strict=True):
            var.unregister(token)
        self._led_tokens = []
        for ch, token in self._channel_led_tokens.items():
            scope.channels[ch].unregister(token)
        self._channel_led_tokens = {}

    @staticmethod
    def _force_leds(scope: Scope) -> None:
        scope.connected.fire_callbacks()
        scope.source_channel.fire_callbacks()
        scope.run.fire_callbacks()
        scope.trigger_source.fire_callbacks()
        scope.trigger_mode.fire_callbacks()
        scope.trigger_edge_slope.fire_callbacks()
        scope.trigger_state.fire_callbacks()
        scope.zoom.fire_callbacks()
        scope.fast_acquire.fire_callbacks()
        scope.touch_enabled.fire_callbacks()
        scope.high_res.fire_callbacks()
        for obs in scope.channels.values():
            obs.fire_callbacks()

    def _reset_leds(self) -> None:
        self.bridge.queue_write("ALL_OFF".encode())

    def _set_led(self, label: str, value: int) -> None:
        self.bridge.queue_write(f"{label}:{value}\n".encode())

    def _cb_source_channel(self, _: Channel, channel: Channel) -> None:
        if channel == Channel.NONE:
            self._set_led("ISEL1", 0)
        else:
            self._set_led(self._sel_led_id(channel), 1)

    @staticmethod
    def _sel_led_id(channel: Channel) -> str:
        if channel is Channel.MATH:
            return "ISEL_M"
        if channel is Channel.BUS:
            return "ISEL_B"
        return f"ISEL{channel.number}"

    def _cb_channel(self, ch: Channel, state: ChannelState) -> None:
        if ch.is_numbered:
            self._set_led(f"IV{ch.number}0", int(state.enabled))
        elif ch == Channel.MATH:
            self._set_led("IVM0", int(state.enabled))
        elif ch == Channel.BUS:
            self._set_led("IVB0", int(state.enabled))
        else:
            logger.error(f"Unknown channel: {ch.label}")

    def _cb_trigger_state(self, _: TriggerState, state: TriggerState) -> None:
        match state:
            case TriggerState.READY | TriggerState.AUTO | TriggerState.ARMED:
                ready = 1
                trig = 0
            case TriggerState.TRIGGERED | TriggerState.SAVE:
                ready = 0
                trig = 1
        self._set_led("ITF0_R", ready)
        self._set_led("ITF0_T", trig)

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
        self._set_led("ITS0_UP", rise)
        self._set_led("ITS0_DN", fall)

    def _cb_trigger_mode(self, _: TriggerMode, mode: TriggerMode) -> None:
        a = mode == TriggerMode.AUTO
        self._set_led("ITM0_A", int(a))
        self._set_led("ITM0_N", int(not a))

    def auto_connect(self) -> None:
        resources = self._rm.list_resources("(USB?*::INSTR|TCPIP?*::INSTR)")

        if not resources:
            logger.info("No scopes found")
        else:
            first = resources[0]
            logger.info(f"Connecting to: {first}")
            if first not in self.scopes:
                self.connect_to_scope(first)
