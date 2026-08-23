#!/bin/bash
# All Off Scene - Everything off
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 0
$CLI set "Ceiling Lights" power 0
$CLI set Bed power 0
$CLI set Mood power 0
$CLI set Kitchen power 0
$CLI set Fan power 0
$CLI set "Uv Light" power 0

echo "All Off scene activated: everything off"