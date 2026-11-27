"""Passive CAN tools for a 2008 Ford F-350 6.4L Power Stroke.

The logger reads SocketCAN and writes candump -L text. It does not send
frames. Bringing an interface up is a separate root helper.
"""

__version__ = "0.1.0"

TZ_NAME = "America/Los_Angeles"
VEHICLE = "2008 Ford F-350 6.4L Powerstroke"
TRANSMISSION = "5R110W TorqShift (TCM integrated in PCM)"
ALLOWED_BITRATES = (125000, 500000)
