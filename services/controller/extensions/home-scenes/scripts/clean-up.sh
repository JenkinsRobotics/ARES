#!/bin/bash
# Clean Up Scene - Productive lighting for cleaning/organizing
# All Nanoleaf lights: 70% brightness, cool white (300 mirek / ~4000K)
# Kitchen OFF, Fan ON for airflow
#
# Bed light quirk: Nanoleaf bulbs in hue/sat mode must have
# saturation set to 0 BEFORE color_temperature will work.

CLI="/Applications/HomeClaw.app/Contents/MacOS/homeclaw-cli"

# Kitchen off (too harsh)
$CLI set Kitchen power 0 2>/dev/null

# Ceiling Light - 70% cool white
$CLI set "Ceiling Light" power 1 2>/dev/null
$CLI set "Ceiling Light" brightness 70 2>/dev/null
$CLI set "Ceiling Light" saturation 0 2>/dev/null
$CLI set "Ceiling Light" color_temperature 300 2>/dev/null

# Ceiling Lights - 70% cool white
$CLI set "Ceiling Lights" power 1 2>/dev/null
$CLI set "Ceiling Lights" brightness 70 2>/dev/null
$CLI set "Ceiling Lights" saturation 0 2>/dev/null
$CLI set "Ceiling Lights" color_temperature 300 2>/dev/null

# Mood - 70% cool white
$CLI set Mood power 1 2>/dev/null
$CLI set Mood brightness 70 2>/dev/null
$CLI set Mood saturation 0 2>/dev/null
$CLI set Mood color_temperature 300 2>/dev/null

# Bed - needs hue/sat cleared first (Nanoleaf quirk)
$CLI set Bed power 1 2>/dev/null
$CLI set Bed brightness 70 2>/dev/null
$CLI set Bed hue 0 2>/dev/null
$CLI set Bed saturation 0 2>/dev/null
sleep 3
$CLI set Bed color_temperature 300 2>/dev/null
$CLI set Bed brightness 70 2>/dev/null

# Fan on for airflow while cleaning
$CLI set Fan power 1 2>/dev/null

echo "Clean Up scene activated: all lights 70% cool white, fan on, kitchen off"