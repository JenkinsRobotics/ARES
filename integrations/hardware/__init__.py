"""ARES Hardware Perception & Adapter Subsystem.

Provides modular abstractions and implementations for physical devices:
  - Cameras ("eyes")
  - Microphones ("ears")
  - Motorized Gimbal / Actuators ("body")
"""

from __future__ import annotations

from integrations.hardware.base import (
    AudioSample,
    BaseAudioAdapter,
    BaseCameraAdapter,
    BasePTZController,
    CameraFrame,
    PTZPosition,
)
from integrations.hardware.insta360 import Insta360Link2

__all__ = [
    "AudioSample",
    "BaseAudioAdapter",
    "BaseCameraAdapter",
    "BasePTZController",
    "CameraFrame",
    "Insta360Link2",
    "PTZPosition",
    "get_hardware_adapter",
]


def get_hardware_adapter() -> Insta360Link2:
    """Factory method returning the primary active hardware adapter."""
    return Insta360Link2()
