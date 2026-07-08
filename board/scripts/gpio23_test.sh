#!/bin/sh
# GPIO23 (GPIO0_C7) 低电平有效 1Hz 测试信号
# 用于继电器/水泵/风扇测试

GPIO=23
PATH=/sys/class/gpio/gpio${GPIO}

echo "=== GPIO${GPIO} (GPIO0_C7) 1Hz 低电平有效测试 ==="

# export
if [ ! -d "$PATH" ]; then
    echo ${GPIO} > /sys/class/gpio/export
    sleep 0.1
fi

echo out > ${PATH}/direction
echo "GPIO${GPIO} 已导出，方向=输出"

# 初始状态：高电平（非激活，继电器断开）
echo 1 > ${PATH}/value
echo "初始状态: 高电平(非激活)"

echo ""
echo "开始 1Hz 测试信号（低电平有效），Ctrl-C 停止..."
echo "格式: [状态] GPIO值"
echo ""

# 1Hz = 周期1秒，低电平有效 = 500ms低 + 500ms高
while true; do
    # 低电平（激活）
    echo 0 > ${PATH}/value
    printf "\r[激活] 0 (低电平)   "
    sleep 0.5

    # 高电平（非激活）
    echo 1 > ${PATH}/value
    printf "\r[空闲] 1 (高电平)   "
    sleep 0.5
done
