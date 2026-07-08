# 🍅 Tomato AI Greenhouse

> 基于边缘AI的番茄温室智能监测与控制系统  
> RV1126B · YOLOv8 · LLM Agent · 数字孪生 · 全端侧离线闭环

[![Platform](https://img.shields.io/badge/platform-RV1126B-blue)](https://www.rock-chips.com/)
[![Python](https://img.shields.io/badge/python-3.11-green)](https://www.python.org/)
[![NPU](https://img.shields.io/badge/NPU-3.0%20TOPS-orange)](https://www.rock-chips.com/)

---

## 📖 项目简介

本系统以嵌入式AI开发板 **ELF-RV1126B** 为核心，在 **完全离线** 的条件下实现温室番茄的智能监测与管理。系统集成计算机视觉、大语言模型Agent、语音交互、多源传感器和执行器控制，是一套面向学科竞赛的端侧AI完整解决方案。

### 核心能力

| 功能 | 描述 | 性能 |
|------|------|:---:|
| 🔍 病虫害检测 | YOLOv8n int8, 13类目标（9病害+健康+3成熟度） | 24-26 FPS |
| 📊 产量估算与预测 | MLP校准模型 + 时序预测器，含7天可采收量 | MAE 7.4g, R²=0.88 |
| 🎤 语音Agent | 离线LLM驱动6工具Agent，支持语音问答与设备控制 | 12.6 tok/s |
| 🌡️ 环境感知 | 三路I2C传感器（光照/CO₂+温湿度/土壤湿度） | 每5秒刷新 |
| ⚙️ 智能执行器 | 病害感知气候管理：风扇/水泵/LED补光自动控制 | 文献驱动策略 |
| 🌐 数字孪生 | React Three Fiber 3D温室 + 实时KPI + 历史趋势 | 手机扫码即达 |

---

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     ELF-RV1126B 边缘板                        │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐     │
│  │ OV13855  │  │ 7"触屏   │  │ USB麦 + 3.5mm喇叭       │     │
│  └────┬─────┘  └────┬─────┘  └───────────┬────────────┘     │
│       │              │                    │                  │
│  ┌────▼──────────────▼────────────────────▼──────────────┐   │
│  │  main_camera_live.py  (YOLOv8 25fps + 触屏UI)         │   │
│  └────┬──────────────┬────────────────────┬──────────────┘   │
│       │              │                    │                  │
│  ┌────▼────┐  ┌──────▼──────┐  ┌─────────▼─────────┐        │
│  │ sensors │  │voice_daemon │  │   crop_web.py      │        │
│  │ (3路I2C)│  │ (Agent 6工具)│  │   :8080            │        │
│  └────┬────┘  └──────┬──────┘  └─────────┬─────────┘        │
│       │              │                    │                  │
│  ┌────▼──────────────▼────────────────────▼──────────────┐   │
│  │  crop-actuator  (风扇+水泵+LED, 病害感知策略)         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              NPU (3 TOPS)                              │    │
│  │  YOLOv8n i8 ∥ Qwen2.5-0.5B W4A16 (时分复用)          │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  云端升级（可选）: GLM-4-Flash | Edge TTS | 天气API   │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
tomato-ai-greenhouse/
├── board/                      # 板端部署代码
│   ├── main_camera_live.py     # 主检测程序（YOLOv8 + 触屏UI）
│   ├── func_yolov8_optimize.py # YOLOv8后处理 + 产量估算
│   ├── crop_web.py             # Web服务 + RESTful API
│   ├── sensors.py              # 三路I2C传感器驱动
│   ├── led_dimmer.py           # 软件PWM LED调光（sysfs）
│   ├── led_driver.py           # LED硬件PWM驱动（备用）
│   ├── actuator.py             # 执行器闭环控制（病害感知）
│   ├── agent_tools.py          # LLM Agent 6工具实现
│   ├── voice_assistant.py      # 语音交互全链路（ASR→LLM→TTS）
│   ├── voice_daemon.py         # 语音常驻守护进程
│   ├── cloud_llm.py            # 云端LLM（GLM-4-Flash）
│   ├── cloud_tts.py            # 云端TTS（Edge TTS）
│   ├── weather.py              # 天气数据注入
│   ├── daily_report.py         # 每日报告生成
│   ├── wechat_push.py          # 微信推送（Server酱）
│   ├── calib_area.py           # 相机面积标定工具
│   ├── gen_cands.py            # 病害告警预合成
│   ├── _npu_coexist.py         # NPU共存测试
│   ├── gpio23_test.py          # GPIO测试工具
│   ├── services/               # systemd 服务文件
│   │   ├── crop-sensors.service
│   │   ├── crop-voice.service
│   │   ├── crop-actuator.service
│   │   ├── crop-web.service
│   │   └── crop-tunnel.service
│   ├── configs/                # 板端配置文件
│   │   ├── asound.conf         # ALSA音频配置（双声道修复）
│   │   ├── 10-noblank.conf     # 禁用屏幕休眠
│   │   ├── crop_detect.desktop # 桌面快捷方式
│   │   └── cloud_config.example.json  # 云端配置模板
│   └── scripts/                # 启动和管理脚本
│       ├── run_live.sh         # 生产环境启动脚本
│       ├── run_demo.sh         # 演示启动脚本
│       ├── setup_rknn_env.sh   # RKNN环境配置
│       └── gpio23_test.sh      # GPIO测试
├── twin/                       # 数字孪生 3D 看板
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/                    # React Three Fiber 源码
│   │   ├── App.jsx             # 主应用（3D温室 + KPI + 逐株）
│   │   ├── Plant.jsx           # 植株3D组件
│   │   ├── Plants.jsx          # 16株排列布局
│   │   ├── Scene.jsx           # 3D场景（温室 + 光照/雾）
│   │   ├── data.js             # 数据获取（API轮询）
│   │   ├── config.js           # 场景配置
│   │   ├── Dashboard.jsx       # KPI仪表盘
│   │   ├── styles.css          # 「清露」液态玻璃设计系统
│   │   └── main.jsx            # 入口
│   └── public/                 # 静态资源
│       └── models/             # 3D模型（需自行放入tomato.glb）
├── training/                   # 模型训练（待补充）
├── models/                     # 模型转换脚本
│   ├── convert_qwen_rkllm.py   # Qwen2.5 → RKLLM 转换
│   └── convert_qwen_w4a16_normal.py  # W4A16量化转换
├── hardware/                    # 硬件设计
│   └── README.md               # 接线图 + 引脚映射
├── docs/                       # 文档
│   ├── tech_report.md          # 英文技术报告
│   └── tech_report_cn.md       # 中文技术报告
└── videos/                     # 演示视频（自行上传）
    └── README.md
```

---

## 🔧 硬件配置

### 核心板
| 项目 | 规格 |
|------|------|
| 型号 | ELF-RV1126B（飞凌嵌入式） |
| SoC | Rockchip RV1126B, 4×A53 @ 1.5GHz |
| NPU | 3.0 TOPS (int8) |
| 内存 | 4GB LPDDR4 |
| 存储 | TF卡（系统）+ /userdata 用户分区 |

### 传感器
| 传感器 | 总线 | 地址 | 测量量 |
|--------|------|:---:|------|
| VEML7700 | i2c-4 | 0x10 | 环境光照 (lux) |
| SCD41 | i2c-4 | 0x62 | CO₂ (ppm) + 温度 + 湿度 |
| ADS1115 + 土壤探头 | i2c-3 | 0x48 | 土壤湿度 (电容式) |

### 执行器
| 设备 | GPIO | 控制方式 | 安全措施 |
|------|:---:|------|------|
| 排风扇 | GPIO4_A1 (129) | 光耦继电器 | PC817隔离 5000Vrms |
| 灌溉水泵 | GPIO3_B7 (111) | 光耦继电器 | PC817隔离 5000Vrms |
| LED补光灯 | GPIO4_A0 (128) | 软件PWM 500Hz | PC817隔离 → 恒流模块EN |

---

## 🧠 AI模型

| 模型 | 框架 | 规格 | 性能 |
|------|------|------|:---:|
| YOLOv8n | RKNN int8, rknnpool×8 | 13类, 640×640 | 25 FPS |
| Qwen2.5-0.5B | RKLLM W4A16 | 576MB, 2048ctx | 12.6 tok/s |
| SenseVoice Small | sherpa-onnx int8 | 229MB | RTF 0.39 |
| Piper huayan-medium | sherpa-onnx | 63MB | RTF 1.18 |

### 检测类别（13类）

**叶部病害**：细菌性斑点 · 早疫病 · 晚疫病 · 叶霉病 · 斑枯病  
**虫害**：潜叶蝇 · 红蜘蛛  
**病毒病**：花叶病毒 · 黄化曲叶病毒  
**健康/成熟度**：健康叶片 · 青果 · 半熟果 · 红果(可采收)

---

## 🚀 快速开始

### 前置条件
- ELF-RV1126B 开发板（Debian 12, Python 3.11）
- 已安装 `rknn-toolkit-lite2 2.3.2`（板端 `/elf-env`）
- YOLOv8 模型文件 `best.rknn` 放入 `board/`（需自行训练/转换）
- 可选：云端 API Key（智谱/阿里百炼）用于云端LLM降级

### 安装步骤

```bash
# 1. 将 board/ 目录推送到板端
adb push board /root/demo/
adb push board/services/* /etc/systemd/system/

# 2. 安装Python依赖（板端）
adb shell pip3 install numpy sherpa-onnx edge-tts

# 3. 安装系统依赖
adb shell apt install espeak-ng sox aplay

# 4. 启用服务
adb shell systemctl enable crop-sensors crop-voice crop-actuator crop-web
adb shell systemctl start crop-sensors crop-voice crop-actuator crop-web

# 5. 启动检测程序
adb shell bash /root/demo/run_live.sh
```

### 访问Web界面
- 局域网：`http://<板子IP>:8080`
- 数字孪生3D看板：`http://<板子IP>:8080/twin/`
- API接口：`http://<板子IP>:8080/api/latest`

---

## 🎯 技术亮点

1. **全端侧离线Agent闭环** — 检测→LLM Agent（6工具）→执行器控制，全部在RV1126B完成
2. **单NPU时分复用** — YOLOv8（8实例池）+ Qwen2.5-0.5B 共享NPU，检测维持25fps
3. **文献驱动的病害感知控制** — 基于22篇权威文献的温湿度/VPD/光照阈值表，根据实际检测到的病害自动切换控制策略
4. **DLI目标补光** — 基于Daily Light Integral (22 mol/m²/day) 的PI控制器，病害时自动提升光照10-20%
5. **红蜘蛛/真菌冲突解决** — 两类病害对湿度需求矛盾（高湿 vs 低湿），priority机制自动折中
6. **数字孪生历史趋势** — CSV历史数据驱动的果实/病害趋势图
7. **断电记忆** — 选株记录 `plants.json` 落盘，重启自动恢复
8. **硬件隔离安全** — 所有执行器经PC817光耦隔离，独立供电，GPIO切换≥0.3s保护间隔

---

## 📚 参考文献（22篇）

### 病害气候管理
- R1: Small (1930) *Ann. Appl. Biol.* — 叶霉温湿度阈值
- R2: Attri et al. (2024) *Plant Archives* — 早疫温湿度阈值
- R3: Maziero et al. (2009) *Plant Disease* — 晚疫温湿度阈值
- R4: Li et al. (2023) *Plant Disease* — 灰霉间歇调节
- R5: Shamshiri et al. (2018) *Int. Agrophys.* — 番茄VPD综述
- R6: Jones et al. (1991) APS Compendium — 番茄病害手册
- R7: Alabama Extension (2023) — 红蜘蛛管理
- R8: NC State Extension (2023) — TYLCV管理
- R9: Wang et al. (2024) *Comp. Elec. Agric.* — MOGA温室优化
- R10: MDPI (2026) *Horticulturae* — 温室病虫害气候综述

### LED补光
- R11: Zhai et al. (2026) *Comp. Elec. Agric.* — DLI目标框架
- R12: Palmitessa et al. (2021) *Acta Hortic.* — 补光阈值
- R13: Lanoue et al. (2026) *Front. Plant Sci.* — 动态光周期
- R14: Wojciechowska et al. (2024) — LED光谱
- R15: *J. Plant Protection Res.* (2024) — 光谱+抗病
- R16: Xu et al. (2026) *Comp. Elec. Agric.* — HLI控制

### 其他
- R17: Hernandez & Kubota (2012) — LED R:B比
- R18: Suarez et al. (2023) — 番茄补光
- R19: Frontiers (2024) — 光周期伤害
- R20: Frontiers (2022) — 冠层下补光
- R21: Rockchip RV1126B Datasheet
- R22: Ultralytics YOLOv8 Docs

---

## 👥 团队分工

| 角色 | 职责 |
|------|------|
| AI算法 | 模型训练/转换/部署（YOLOv8 + LLM） |
| 嵌入式集成 | 摄像头/传感器/系统/执行器接线 |
| 数据展示 | 数据标注/UI/Web/数字孪生/文档 |

---

## 📹 演示视频
视频已发布在【嵌入式芯片与系统设计大赛--基于边缘AI的番茄温室智能监测与控制系统】 https://www.bilibili.com/video/BV1L5MV6SEVY/?share_source=copy_web&vd_source=042107418a6d7cacf261f0ebb8438c8d



