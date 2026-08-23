#!/bin/bash
# Movie Scene - Very dim warm light for watching
# Ceiling off, bed + mood at 10-15% very warm, fan off
CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

$CLI set "Ceiling Light" power 0
$CLI set "Ceiling Lights" power 0
$CLI set Bed power 1
$CLI set Bed brightness 15
$CLI set Bed color_temperature 450
$CLI set Mood power 1
$CLI set Mood brightness 10
$CLI set Mood color_temperature 450
$CLI set Fan power 0

echo "Movie scene activated: very dim warm light"