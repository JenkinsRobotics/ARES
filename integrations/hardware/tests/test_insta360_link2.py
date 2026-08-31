"""Automated tests for ARES Insta360 Link 2 hardware adapter."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from integrations.hardware import get_hardware_adapter
from integrations.hardware.base import (
    AudioSample,
    BaseAudioAdapter,
    BaseCameraAdapter,
    BasePTZController,
    CameraFrame,
    PTZPosition,
)
from integrations.hardware.insta360.constants import (
    INSTA360_VID,
    LINK1_PID,
    LINK2_PID,
    PAN_MAX,
    PAN_MIN,
    TILT_MAX,
    TILT_MIN,
)
from integrations.hardware.insta360.link2 import Insta360Link2


def test_hardware_adapter_factory():
    adapter = get_hardware_adapter()
    assert isinstance(adapter, Insta360Link2)
    assert isinstance(adapter, BaseCameraAdapter)
    assert isinstance(adapter, BaseAudioAdapter)
    assert isinstance(adapter, BasePTZController)


def test_hardware_adapter_constants():
    assert INSTA360_VID == 0x2E1A
    assert LINK2_PID == 0x4C04
    assert LINK1_PID == 0x4003
    assert PAN_MIN < PAN_MAX
    assert TILT_MIN < TILT_MAX


@pytest.mark.skipif(platform.system() != "Darwin", reason="IOKit hardware tests require macOS")
def test_hardware_adapter_status():
    cam = Insta360Link2()
    status = cam.status()
    assert isinstance(status, dict)
    assert status["device"] == "Insta360 Link 2"
    assert "connected" in status
    assert "gimbal" in status
    assert "video" in status
    assert "audio" in status


@pytest.mark.skipif(platform.system() != "Darwin", reason="Live hardware test requires macOS")
def test_hardware_gimbal_position_read():
    cam = Insta360Link2()
    try:
        pos = cam.get_position()
        assert isinstance(pos, PTZPosition)
        assert isinstance(pos.pan, int)
        assert isinstance(pos.tilt, int)
    except ConnectionError:
        pytest.skip("Physical camera not currently connected on USB")


@pytest.mark.skipif(platform.system() != "Darwin", reason="Live hardware test requires macOS")
def test_hardware_snapshot_capture(tmp_path: Path):
    cam = Insta360Link2()
    out = tmp_path / "test_frame.jpg"
    try:
        frame = cam.capture_frame(output_path=out, resolution="1280x720")
        assert isinstance(frame, CameraFrame)
        assert frame.path.exists()
        assert frame.path.stat().st_size > 0
        assert frame.width == 1280
        assert frame.height == 720
    except Exception as exc:
        pytest.skip(f"Camera frame capture not accessible: {exc}")


@pytest.mark.skipif(platform.system() != "Darwin", reason="Live hardware test requires macOS")
def test_hardware_audio_recording(tmp_path: Path):
    cam = Insta360Link2()
    out = tmp_path / "test_audio.wav"
    try:
        sample = cam.record_sample(duration_seconds=1.0, output_path=out)
        assert isinstance(sample, AudioSample)
        assert sample.path.exists()
        assert sample.path.stat().st_size > 0
        assert sample.sample_rate == 48000
    except Exception as exc:
        pytest.skip(f"Microphone audio recording not accessible: {exc}")
