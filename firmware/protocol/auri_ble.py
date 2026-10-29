"""Re-export of the Auri strap decoder.

The single copy lives in ``hub/physiobuddy_hub/straps/protocol.py``. Firmware tools keep importing this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HUB_ROOT = Path(__file__).resolve().parents[2] / "hub"
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

from physiobuddy_hub.straps.protocol import *  # noqa: E402,F403
