"""Make XLeRobot's network clients work under lerobot and Strands.

- Upstream ``lerobot_robot_xlerobot`` registers ``XLerobotClientConfig`` but its
  ``__init__`` leaves ``XLerobotClient`` commented out, so lerobot's
  ``make_device_from_device_class`` (which looks for the class on the config's
  parent package) cannot find it.
- Both XLeRobot clients define ``connect(self)``, while lerobot's ``Robot`` API (and
  Strands, which calls ``robot.connect(False)``) passes ``calibrate``. A client has
  nothing to calibrate, so the argument is accepted and ignored.

The ``lerobot_robot_`` prefix makes both lerobot and Strands import this package at
plugin-discovery time.
"""

import functools

import lerobot_robot_xlerobot
from lerobot_robot_xlerobot.xlerobot_client import XLerobotClient

lerobot_robot_xlerobot.XLerobotClient = XLerobotClient


def _accept_calibrate(cls) -> None:
    original = cls.connect

    @functools.wraps(original)
    def connect(self, calibrate: bool = True) -> None:
        original(self)

    cls.connect = connect


_accept_calibrate(XLerobotClient)

try:
    from lerobot_robot_xlerobot_2wheels import XLerobot2WheelsClient
except ImportError:
    XLerobot2WheelsClient = None
else:
    _accept_calibrate(XLerobot2WheelsClient)

__all__ = ["XLerobotClient", "XLerobot2WheelsClient"]
