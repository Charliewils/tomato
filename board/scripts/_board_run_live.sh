#!/bin/bash
export DISPLAY=:0
export XAUTHORITY=/root/.Xauthority
pkill -f main_camera_live.py 2>/dev/null
sleep 1
cd /root/demo
exec /elf-env/bin/python3 main_camera_live.py >/root/demo/live.log 2>&1
