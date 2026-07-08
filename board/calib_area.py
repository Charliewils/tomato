"""测 YieldCalibrator 旋钮1 CROP_AREA_SCALE。

跑 YOLOv8 检测, 收集青/半/红果检测框平均面积(640空间, 与 myFunc 一致),
按 CROP_AREA_SCALE = 训练均值 / 实测均值 给出建议值。

用法(板上, /root/demo):
    /elf-env/bin/python3 calib_area.py v4pick v4test unseen   # 图集模式
    /elf-env/bin/python3 calib_area.py --camera 60            # 现场实时相机60帧(最准)
"""
import os, sys, glob
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rknnpool.rknnpool_ld import initRKNN
from func.func_yolov8_optimize import myFunc

FRUIT = ["green", "half_ripened", "fully_ripened"]
TRAIN = {"green": 247.0, "half_ripened": 712.0, "fully_ripened": 1020.6}  # 合成训练框面积均值(px²)
CN = {"green": "青果", "half_ripened": "半熟", "fully_ripened": "完熟"}
MODEL = "./rknnModel/best.rknn"
DEV = "/dev/video52"


def frames_from_camera(n):
    cap = cv2.VideoCapture(DEV)
    if not cap.isOpened():
        print("相机打不开:", DEV); return
    for _ in range(5):                 # 丢弃预热帧
        cap.read()
    got = 0
    while got < n:
        ret, fr = cap.read()
        if not ret:
            break
        got += 1
        yield fr
    cap.release()


def frames_from_dirs(dirs):
    for d in dirs:
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG"):
            for p in glob.glob(os.path.join(d, ext)):
                im = cv2.imread(p)
                if im is not None:
                    yield im


def main():
    args = sys.argv[1:]
    if args and args[0] == "--camera":
        n = int(args[1]) if len(args) > 1 else 60
        src, label = frames_from_camera(n), "相机 %d 帧" % n
    else:
        dirs = args or ["v4pick", "v4test", "unseen"]
        src, label = frames_from_dirs(dirs), "图集 %s" % dirs

    rknn = initRKNN(MODEL)
    asum = {k: 0.0 for k in FRUIT}
    cnt = {k: 0 for k in FRUIT}
    nframe = 0
    for im in src:
        nframe += 1
        _, counts, area_sum = myFunc(rknn, im)
        for k in FRUIT:
            asum[k] += area_sum.get(k, 0.0)
            cnt[k] += counts.get(k, 0)
    rknn.release()

    print("\n来源: %s  共 %d 帧" % (label, nframe))
    print("-" * 56)
    ratios = []
    for k in FRUIT:
        if cnt[k] > 0:
            m = asum[k] / cnt[k]
            r = TRAIN[k] / m
            ratios.append(r)
            print("%s: 样本%4d  实测均值%7.0f  训练%6.0f  比例 %.3f"
                  % (CN[k], cnt[k], m, TRAIN[k], r))
        else:
            print("%s: 无样本(该类未检出, 跳过)" % CN[k])
    print("-" * 56)
    if ratios:
        scale = sum(ratios) / len(ratios)
        print("建议  CROP_AREA_SCALE ≈ %.3f   (%d 类比例均值)" % (scale, len(ratios)))
        print("设置: 在 run_live.sh 加  export CROP_AREA_SCALE=%.3f" % scale)
    else:
        print("未检出任何果实, 无法标定。换含果实的图或对准番茄。")


if __name__ == "__main__":
    main()
