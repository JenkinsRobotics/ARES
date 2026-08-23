#!/bin/bash
# Focus Scene - Bright cool light for working
# All ceiling lights on full, desk/ambient lights off, fan on
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 1
$CLI set "Ceiling Light" brightness 100
$CLI set "Ceiling Light" color_temperature 300
$CLI set "Ceiling Lights" power 1
$CLI set "Ceiling Lights" brightness 100
$CLI set "Ceiling Lights" color_temperature 300
$CLI set Bed power 0
$CLI set Mood power 0
$CLI set Fan power 1

echo "Focus scene activated: bright cool light, fan on"