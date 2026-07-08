#!/bin/bash
set -e

echo "=== [1/6] 更新 apt 源 ==="
sudo apt-get update -y

echo "=== [2/6] 安装系统依赖 ==="
sudo apt-get install -y \
    libxslt1-dev zlib1g zlib1g-dev libglib2.0-0 \
    libsm6 libgl1-mesa-glx libprotobuf-dev gcc git wget

echo "=== [3/6] 下载并安装 Miniconda（清华镜像）==="
if [ ! -f ~/miniconda3/bin/conda ]; then
    wget -q https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh \
        -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p ~/miniconda3
    rm /tmp/miniconda.sh
fi
export PATH="$HOME/miniconda3/bin:$PATH"
eval "$(~/miniconda3/bin/conda shell.bash hook)"
conda init bash
source ~/.bashrc

echo "=== [4/6] 创建 rknn1 环境（Python 3.8）==="
conda create -n rknn1 python=3.8 -y

echo "=== [5/6] 激活环境并安装依赖 ==="
conda activate rknn1

# rknn-toolkit v1 whl 需要手动从 GitHub 下载，先装其他依赖
pip install torch==1.10.1+cpu torchvision==0.11.2+cpu \
    -f https://download.pytorch.org/whl/torch_stable.html
pip install onnx==1.10.2 opencv-python flask numpy

echo "=== [6/6] 克隆 airockchip YOLOv5 ==="
if [ ! -d ~/yolov5 ]; then
    git clone https://github.com/airockchip/yolov5.git ~/yolov5
    pip install -r ~/yolov5/requirements.txt
fi

echo ""
echo "=============================="
echo " 基础环境安装完成！"
echo "=============================="
echo ""
echo "下一步：安装 rknn-toolkit v1 whl"
echo "  1. 先在板端执行：strings /usr/lib/librknnrt.so | grep version"
echo "  2. 从 https://github.com/rockchip-linux/rknn-toolkit/releases 下载对应版本"
echo "  3. 在 rknn1 环境执行：pip install rknn_toolkit-1.x.x-cp38-cp38-linux_x86_64.whl"
echo "  4. 验证：python3 -c \"from rknn.api import RKNN; print('OK')\""
