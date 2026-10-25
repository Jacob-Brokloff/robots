"""Make ``--robot.type=xlerobot_client`` constructible.

Upstream ``lerobot_robot_xlerobot`` registers ``XLerobotClientConfig`` but its
``__init__`` leaves ``XLerobotClient`` commented out, so lerobot's
``make_device_from_device_class`` (which looks for the class on the config's
parent package) cannot find it. The ``lerobot_robot_`` prefix makes both lerobot
and Strands import this package at plugin-discovery time.
"""

import lerobot_robot_xlerobot
from lerobot_robot_xlerobot.xlerobot_client import XLerobotClient

lerobot_robot_xlerobot.XLerobotClient = XLerobotClient

__all__ = ["XLerobotClient"]
