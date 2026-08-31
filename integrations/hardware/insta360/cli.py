"""CLI utility for inspecting and controlling the Insta360 Link 2 camera in ARES."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from integrations.hardware.insta360.link2 import Insta360Link2


def main():
    parser = argparse.ArgumentParser(description="ARES Insta360 Link 2 Hardware Controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    subparsers.add_parser("status", help="Show connection status and current gimbal position")

    # snapshot
    snap_parser = subparsers.add_parser("snapshot", help="Capture a single frame from the camera")
    snap_parser.add_argument("--output", "-o", type=Path, default=None, help="Output image file path")
    snap_parser.add_argument("--res", "-r", type=str, default="1920x1080", help="Resolution (e.g. 1920x1080, 1280x720)")

    # listen
    listen_parser = subparsers.add_parser("listen", help="Record an audio clip from the microphone")
    listen_parser.add_argument("--duration", "-d", type=float, default=3.0, help="Duration in seconds")
    listen_parser.add_argument("--output", "-o", type=Path, default=None, help="Output wav file path")

    # center
    subparsers.add_parser("center", help="Reset gimbal to center")

    # deskview
    subparsers.add_parser("deskview", help="Tilt gimbal downward to view desk/paperwork")

    # aim
    aim_parser = subparsers.add_parser("aim", help="Move gimbal to specific pan and tilt")
    aim_parser.add_argument("--pan", "-p", type=int, required=True, help="Pan value (-540000 to 540000)")
    aim_parser.add_argument("--tilt", "-t", type=int, required=True, help="Tilt value (-360000 to 360000)")

    args = parser.parse_args()
    cam = Insta360Link2()

    if args.command == "status":
        info = cam.status()
        print(json.dumps(info, indent=2))

    elif args.command == "snapshot":
        frame = cam.capture_frame(output_path=args.output, resolution=args.res)
        print(f"Captured frame to: {frame.path} ({frame.width}x{frame.height}, {frame.format})")

    elif args.command == "listen":
        sample = cam.record_sample(duration_seconds=args.duration, output_path=args.output)
        print(f"Recorded audio to: {sample.path} ({sample.duration_seconds}s, {sample.sample_rate}Hz)")

    elif args.command == "center":
        pos = cam.center()
        print(f"Gimbal centered: pan={pos.pan}, tilt={pos.tilt}")

    elif args.command == "deskview":
        pos = cam.deskview()
        print(f"Gimbal in DeskView: pan={pos.pan}, tilt={pos.tilt}")

    elif args.command == "aim":
        pos = cam.aim(pan=args.pan, tilt=args.tilt)
        print(f"Gimbal aimed to: pan={pos.pan}, tilt={pos.tilt}")


if __name__ == "__main__":
    main()
