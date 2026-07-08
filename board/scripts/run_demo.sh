#!/bin/bash
source /elf-env/bin/activate
cd /root/demo
xset s off
xset -dpms
exec python3 main_camera_live.py
