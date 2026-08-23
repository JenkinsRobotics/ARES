#!/bin/bash
# Sleep Scene - Everything off, fan on
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 0
$CLI set "Ceiling Lights" power 0
$CLI set Bed power 0
$CLI set Mood power 0
$CLI set Kitchen power 0
$CLI set Fan power 1
$CLI set "Uv Light" power 0

echo "Sleep scene activated: all lights off, fan on"