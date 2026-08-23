#!/bin/bash
# Custom light control - pass light name, characteristic, value
# Usage: ./set-light.sh <light_name> <characteristic> <value>
# Examples:
#   ./set-light.sh "Mood" brightness 75
#   ./set-light.sh "Bed" power 1
#   ./set-light.sh "Ceiling Light" color_temperature 350
#   ./set-light.sh "Mood" hue 120

CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

if [ $# -lt 3 ]; then
    echo "Usage: $0 <accessory_name> <characteristic> <value>"
    echo ""
    echo "Accessories:"
    echo "  Ceiling Light, Ceiling Lights, Bed, Mood"
    echo "  Fan, Kitchen, Garage, Internet, Uv Light, Computer"
    echo "  Garage Door, garage Door, Indoor Cam Pan & Tilt"
    echo ""
    echo "Characteristics for lights:"
    echo "  power (0=off, 1=on)"
    echo "  brightness (0-100)"
    echo "  color_temperature (153-500, lower=cooler, higher=warmer)"
    echo "  hue (0-360)"
    echo "  saturation (0-100)"
    echo ""
    echo "Characteristics for outlets/switches:"
    echo "  power (true=on, false=off)"
    echo ""
    echo "Color temperature guide:"
    echo "  153 = coolest/daylight (6500K)"
    echo "  300 = cool white (4000K) - good for focus"
    echo "  350 = neutral white (3000K)"
    echo "  400 = warm white (2500K) - relaxing"
    echo "  450 = very warm (2200K) - cozy/bedtime"
    echo "  500 = warmest candle-like (2000K)"
    exit 1
fi

ACCESSORY="$1"
CHAR="$2"
VALUE="$3"

$CLI set "$ACCESSORY" "$CHAR" "$VALUE"