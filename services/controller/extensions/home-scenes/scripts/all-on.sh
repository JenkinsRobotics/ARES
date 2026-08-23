#!/bin/bash
# All On Scene - Every light at full brightness
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 1
$CLI set "Ceiling Light" brightness 100
$CLI set "Ceiling Lights" power 1
$CLI set "Ceiling Lights" brightness 100
$CLI set Bed power 1
$CLI set Bed brightness 100
$CLI set Mood power 1
$CLI set Mood brightness 100
$CLI set Fan power 1

echo "All On scene activated: all lights at full brightness"