#!/bin/bash
# Relax Scene - Warm dim ambient light
# Ceiling off, bed + mood at 50% warm, fan on
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 0
$CLI set "Ceiling Lights" power 0
$CLI set Bed power 1
$CLI set Bed brightness 50
$CLI set Bed color_temperature 400
$CLI set Mood power 1
$CLI set Mood brightness 50
$CLI set Mood color_temperature 400
$CLI set Fan power 1

echo "Relax scene activated: warm dim ambient light"