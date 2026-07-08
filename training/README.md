# 模型训练

## YOLOv8 检测模型

### 数据集
训练使用自定义番茄田间数据集，包含13类标注：
- 叶部病害：细菌性斑点、早疫病、晚疫病、叶霉病、斑枯病
- 虫害：潜叶蝇、红蜘蛛
- 病毒病：花叶病毒、黄化曲叶病毒
- 健康/成熟度：健康叶片、青果、半熟果、红果

### 训练环境
- GPU: RTX 4090D
- 框架: airockchip/ultralytics (YOLOv8)
- 输入尺寸: 640×640

### 模型转换
```bash
# ONNX → RKNN (在 WSL rknn-toolkit2 环境中)
cd rknn_model_zoo/examples/yolov8/python/
python3 convert.py model.onnx rv1126b i8 best.rknn
```

⚠️ 注意：ckpt/onnx/rknn 模型文件因体积较大未包含在仓库中，需自行训练或从官方渠道获取。

## Qwen2.5-0.5B LLM 模型

### 转换脚本
```bash
# W4A16 量化转换（推荐，12.6 tok/s）
python3 models/convert_qwen_w4a16_normal.py

# 部署到板端
adb push model.rkllm /userdata/llm/models/
```

### 依赖
- RKLLM toolkit 1.2.3
- 转换环境：WSL Ubuntu (Python 3.10+)
- 目标平台：RV1126B

## 产量模型

两个MLP模型在板端以纯numpy推理：
- **YieldCalibratorCPU**: 291参数，MAE 7.4g, R²=0.88
- **YieldPredictorCPU**: 545参数，R²=0.59

模型权重（.npz）需放入 `/root/demo/` 目录。
