from pyvisa.resources import MessageBasedResource

from tekafp.input import ControlType, EncoderControl, Input
from tekafp.registry import Registry


# function types:
# encoder
#   - query current value
#   - data transform with +-1 encoder value and step scaler
#   - clamp
#   - write back
# cycle (stateful)
#   - query current value
#   - flow is like: if current is A, then new is B, else C
#   - write back
# opaque (stateless)
#   - if pressed, write a command (TRIGGER FORCE, fastacq, ...)

control_registry: Registry[str, ControlType] = Registry()

control_registry.register("VP1", EncoderControl())

def func(scope: MessageBasedResource, state: dict[str, str], inp: Input,
         **kwargs: int) -> None:
    pass