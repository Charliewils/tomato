#!/bin/bash
export DISPLAY=:0
export XAUTHORITY=/root/.Xauthority
export CROP_AREA_SCALE=0.193        # 旋钮1: calib_area.py 数据集图实测; 现场用 calib_area.py --camera 重测
export CROP_PLANT_DATE=2026-04-15   # 旋钮2: 番茄定植日(春茬中性默认), 知道实际日期请改
pkill -f main_camera_live.py 2>/dev/null
sleep 1
cd /root/demo
exec /elf-env/bin/python3 main_camera_live.py >/root/demo/live.log 2>&1
