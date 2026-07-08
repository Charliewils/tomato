# 以下代码改自https://github.com/rockchip-linux/rknn-toolkit2/tree/master/examples/onnx/yolov5
import cv2
import numpy as np
import os, sys
from copy import copy
OBJ_THRESH, NMS_THRESH, IMG_SIZE = 0.25, 0.45, 640
out_win = "output_style_full_screen"
CLASSES = ("bacterial_spot", "early_blight", "healthy", "late_blight", "leaf_mold",
           "leaf_miner", "mosaic_virus", "septoria", "spider_mites",
           "yellow_leaf_curl_virus", "fully_ripened", "green", "half_ripened")

INTERESTED_CLASSES = ["bacterial_spot", "early_blight", "healthy", "late_blight", "leaf_mold",
                      "leaf_miner", "mosaic_virus", "septoria", "spider_mites",
                      "yellow_leaf_curl_virus", "fully_ripened", "green", "half_ripened"]



CLASS_INDICES = {cls: idx for idx, cls in enumerate(CLASSES)}
INTERESTED_CLASS_INDICES = [CLASS_INDICES[cls] for cls in INTERESTED_CLASSES]
HEALTHY_IDX = CLASSES.index("healthy")  # 正常叶不检测(省算力+免框太多)
def filter_boxes(boxes, box_confidences, box_class_probs):
    """Filter boxes with object threshold.
    """
    box_confidences = box_confidences.reshape(-1)
    candidate, class_num = box_class_probs.shape

    class_max_score = np.max(box_class_probs, axis=-1)
    classes = np.argmax(box_class_probs, axis=-1)

    _class_pos = np.where(class_max_score * box_confidences >= OBJ_THRESH)
    scores = (class_max_score * box_confidences)[_class_pos]

    boxes = boxes[_class_pos]
    classes = classes[_class_pos]

    return boxes, classes, scores


def nms_boxes(boxes, scores):
    """Suppress non-maximal boxes.
    # Returns
        keep: ndarray, index of effective boxes.
    """
    x = boxes[:, 0]
    y = boxes[:, 1]
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]

    areas = w * h
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        xx1 = np.maximum(x[i], x[order[1:]])
        yy1 = np.maximum(y[i], y[order[1:]])
        xx2 = np.minimum(x[i] + w[i], x[order[1:]] + w[order[1:]])
        yy2 = np.minimum(y[i] + h[i], y[order[1:]] + h[order[1:]])

        w1 = np.maximum(0.0, xx2 - xx1 + 0.00001)
        h1 = np.maximum(0.0, yy2 - yy1 + 0.00001)
        inter = w1 * h1

        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(ovr <= NMS_THRESH)[0]
        order = order[inds + 1]
    keep = np.array(keep)
    return keep


# def dfl(position):
#     # Distribution Focal Loss (DFL)
#     import torch
#     x = torch.tensor(position)
#     n,c,h,w = x.shape
#     p_num = 4
#     mc = c//p_num
#     y = x.reshape(n,p_num,mc,h,w)
#     y = y.softmax(2)
#     acc_metrix = torch.tensor(range(mc)).float().reshape(1,1,mc,1,1)
#     y = (y*acc_metrix).sum(2)
#     return y.numpy()

# def dfl(position):
#     # Distribution Focal Loss (DFL)
#     n, c, h, w = position.shape
#     p_num = 4
#     mc = c // p_num
#     y = position.reshape(n, p_num, mc, h, w)
#     exp_y = np.exp(y)
#     y = exp_y / np.sum(exp_y, axis=2, keepdims=True)
#     acc_metrix = np.arange(mc).reshape(1, 1, mc, 1, 1).astype(float)
#     y = (y * acc_metrix).sum(2)
#     return y

def dfl(position):
    # Distribution Focal Loss (DFL)
    # x = np.array(position)
    n, c, h, w = position.shape
    p_num = 4
    mc = c // p_num
    y = position.reshape(n, p_num, mc, h, w)

    # Vectorized softmax
    e_y = np.exp(y - np.max(y, axis=2, keepdims=True))  # subtract max for numerical stability
    y = e_y / np.sum(e_y, axis=2, keepdims=True)

    acc_metrix = np.arange(mc).reshape(1, 1, mc, 1, 1)
    y = (y * acc_metrix).sum(2)
    return y


def box_process(position):
    grid_h, grid_w = position.shape[2:4]
    col, row = np.meshgrid(np.arange(0, grid_w), np.arange(0, grid_h))
    col = col.reshape(1, 1, grid_h, grid_w)
    row = row.reshape(1, 1, grid_h, grid_w)
    grid = np.concatenate((col, row), axis=1)
    stride = np.array([IMG_SIZE // grid_h, IMG_SIZE // grid_w]).reshape(1, 2, 1, 1)

    position = dfl(position)
    box_xy = grid + 0.5 - position[:, 0:2, :, :]
    box_xy2 = grid + 0.5 + position[:, 2:4, :, :]
    xyxy = np.concatenate((box_xy * stride, box_xy2 * stride), axis=1)

    return xyxy


def yolov8_post_process(input_data):
    boxes, scores, classes_conf = [], [], []
    defualt_branch = 3
    pair_per_branch = len(input_data) // defualt_branch
    # Python 忽略 score_sum 输出
    for i in range(defualt_branch):
        boxes.append(box_process(input_data[pair_per_branch * i]))
        classes_conf.append(input_data[pair_per_branch * i + 1])
        scores.append(np.ones_like(input_data[pair_per_branch * i + 1][:, :1, :, :], dtype=np.float32))

    def sp_flatten(_in):
        ch = _in.shape[1]
        _in = _in.transpose(0, 2, 3, 1)
        return _in.reshape(-1, ch)

    boxes = [sp_flatten(_v) for _v in boxes]
    classes_conf = [sp_flatten(_v) for _v in classes_conf]
    scores = [sp_flatten(_v) for _v in scores]

    boxes = np.concatenate(boxes)
    classes_conf = np.concatenate(classes_conf)
    scores = np.concatenate(scores)

    # filter according to threshold
    boxes, classes, scores = filter_boxes(boxes, scores, classes_conf)

    # 丢弃 healthy: 正常叶占多数,框多且耗算力,不检测
    keep = classes != HEALTHY_IDX
    boxes, classes, scores = boxes[keep], classes[keep], scores[keep]

    # nms
    nboxes, nclasses, nscores = [], [], []
    for c in set(classes):
        inds = np.where(classes == c)
        b = boxes[inds]
        c = classes[inds]
        s = scores[inds]
        keep = nms_boxes(b, s)

        if len(keep) != 0:
            nboxes.append(b[keep])
            nclasses.append(c[keep])
            nscores.append(s[keep])

    if not nclasses and not nscores:
        return None, None, None

    boxes = np.concatenate(nboxes)
    classes = np.concatenate(nclasses)
    scores = np.concatenate(nscores)

    return boxes, classes, scores

def draw_box_corner(draw_img, top, left, right, bottom, length, corner_color):
    # Top Left
    cv2.line(draw_img, (top, left), (top + length, left), corner_color, thickness=3)
    cv2.line(draw_img, (top, left), (top, left + length), corner_color, thickness=3)
    # Top Right
    cv2.line(draw_img, (right, left), (right - length, left), corner_color, thickness=3)
    cv2.line(draw_img, (right, left), (right, left + length), corner_color, thickness=3)
    # Bottom Left
    cv2.line(draw_img, (top, bottom), (top + length, bottom), corner_color, thickness=3)
    cv2.line(draw_img, (top, bottom), (top, bottom - length), corner_color, thickness=3)
    # Bottom Right
    cv2.line(draw_img, (right, bottom), (right - length, bottom), corner_color, thickness=3)
    cv2.line(draw_img, (right, bottom), (right, bottom - length), corner_color, thickness=3)
def draw_label_type(draw_img, top, left, CLASSES, label_color):
    label = str(CLASSES)
    labelSize = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1, 6)[0]

    # 计算文本边界框的位置
    if left - labelSize[1] - 3 < 0:  # 如果标签在图像左侧放不下
        # 在标签右侧绘制背景框和文本
        box_coords = (top, left + 5, top + labelSize[0], left + labelSize[1] + 3)
        text_pos = (top, left + labelSize[0] + 3)  # 文本放置在背景框右侧
    else:
        # 在标签左侧绘制背景框和文本
        box_coords = (top, left - labelSize[1] - 3, top + labelSize[0], left - 3)
        text_pos = (top, left - 3)  # 文本放置在背景框左侧

    # 绘制背景框
    cv2.rectangle(draw_img, box_coords[0:2], box_coords[2:4], color=label_color, thickness=-1)

    # 在背景框上绘制文本
    cv2.putText(draw_img, label, text_pos, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), thickness=2)


# def draw(image, boxes, scores, classes, ratio, padding):
#     for box, score, cl in zip(boxes, scores, classes):
#         top, left, right, bottom = box
#
#         top = (top - padding[0]) / ratio[0]
#         left = (left - padding[1]) / ratio[1]
#         right = (right - padding[0]) / ratio[0]
#         bottom = (bottom - padding[1]) / ratio[1]
#         # print('class: {}, score: {}'.format(CLASSES[cl], score))
#         # print('box coordinate left,top,right,down: [{}, {}, {}, {}]'.format(top, left, right, bottom))
#         top = int(top)
#         left = int(left)
#
#         cv2.rectangle(image, (top, left), (int(right), int(bottom)), (255, 0, 0), 2)
#         cv2.putText(image, '{0} {1:.2f}'.format(CLASSES[cl], score),
#                     (top, left - 6),
#                     cv2.FONT_HERSHEY_SIMPLEX,
#                     0.6, (0, 0, 255), 2)

def draw(image, boxes, scores, classes, ratio, padding):
    for box, score, cl in zip(boxes, scores, classes):
            top, left, right, bottom = box

            top = int((top - padding[0]) / ratio[0])
            left = int((left - padding[1]) / ratio[1])
            right = int((right - padding[0]) / ratio[0])
            bottom = int((bottom - padding[1]) / ratio[1])

            cv2.rectangle(image, (top,left), (right, bottom), (255,0,255), 2)
            draw_box_corner(image, top, left, right, bottom, 15, (0, 255, 0))
            draw_label_type(image, top, left,CLASSES[cl], (255,0,255))



def letterbox(im, new_shape=(640, 640), color=(0, 0, 0)):
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

    ratio = r, r  # width, height ratios
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - \
             new_unpad[1]  # wh padding

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize——
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right,
                            cv2.BORDER_CONSTANT, value=color)  # add border
    # return im
    return im, ratio, (left, top)


FRUIT_WEIGHT_G = {"green": 90, "half_ripened": 120, "fully_ripened": 150}  # 模型加载失败时的兜底固定均重(g)
DISEASE_NAMES = [c for c in CLASSES if c not in ("green", "half_ripened", "fully_ripened", "healthy")]


# 动态单果估重: 直接复用官方 deploy/yield_inference.py(单一可信源,重训只需替换该文件+npz)
# 面积量纲/生长天数两旋钮(CROP_AREA_SCALE/CROP_PLANT_DATE)与±3σ截断都在 wrapper 内


def _find(*names):
    here = os.path.dirname(os.path.abspath(__file__))
    for b in (os.environ.get("CROP_DEPLOY_DIR", ""), here, os.path.join(here, ".."),
              ".", "rknnModel", "/root/demo"):
        for nm in names:
            p = os.path.join(b, nm) if b else nm
            if os.path.exists(p):
                return os.path.abspath(p)
    return None


_YI = {"loaded": False, "cal": None}


def _calibrator():
    if not _YI["loaded"]:
        _YI["loaded"] = True
        try:
            yi = _find("yield_inference.py")
            d = os.path.dirname(yi) if yi else None
            if d and d not in sys.path:
                sys.path.insert(0, d)
            from yield_inference import YieldCalibratorCPU
            npz = _find("yield_calibrator_params.npz")
            _YI["cal"] = YieldCalibratorCPU(npz) if npz else None
        except Exception:
            _YI["cal"] = None
    return _YI["cal"]


def estimate_yield(counts, areas=None, day=None):
    g = counts.get("green", 0); h = counts.get("half_ripened", 0); r = counts.get("fully_ripened", 0)
    cal = _calibrator()
    if cal is not None:
        a = areas or {}
        m = cal.scaler_mean
        out = cal.predict(g, h, r, a.get("green", m[3]), a.get("half_ripened", m[4]),
                          a.get("fully_ripened", m[5]), day)
        w = {"green": float(out[0]), "half_ripened": float(out[1]), "fully_ripened": float(out[2])}
    else:
        w = FRUIT_WEIGHT_G                       # wrapper/npz 缺失时兜底
    wt_total = g * w["green"] + h * w["half_ripened"] + r * w["fully_ripened"]
    wt_ripe = r * w["fully_ripened"]
    return w, wt_total, wt_ripe


CN = {"green": "青果", "half_ripened": "半熟", "fully_ripened": "红果", "healthy": "健康",
      "bacterial_spot": "细菌性斑点", "early_blight": "早疫病", "late_blight": "晚疫病",
      "leaf_mold": "叶霉病", "leaf_miner": "潜叶蝇", "mosaic_virus": "花叶病毒",
      "septoria": "斑枯病", "spider_mites": "红蜘蛛", "yellow_leaf_curl_virus": "黄化曲叶病毒"}
ADVICE = {"bacterial_spot": "选无病种子;铜制剂喷雾;避免叶面长时间湿润;清除病残体",
          "early_blight": "及时摘除病叶;代森锰锌或苯醚甲环唑喷雾;合理密植通风;轮作",
          "late_blight": "雨后及时排湿;烯酰吗啉或霜霉威防治;清除病株;降低田间湿度",
          "leaf_mold": "降低棚内湿度并通风;百菌清或苯醚甲环唑;摘除病叶;控制夜间结露",
          "leaf_miner": "黄板诱杀成虫;阿维菌素或灭蝇胺喷雾;清除有虫道的叶片",
          "mosaic_virus": "重点防治蚜虫(传毒媒介);拔除病株;接触前洗手消毒工具;选抗病品种",
          "septoria": "摘除下部病叶;代森锰锌或百菌清;避免叶面浇水;清园轮作",
          "spider_mites": "适当提高湿度抑螨;哒螨灵或阿维菌素;清除杂草;可释放捕食螨",
          "yellow_leaf_curl_virus": "防治烟粉虱(传毒);用防虫网隔离;及时拔除病株;选抗病品种"}
try:
    from PIL import Image, ImageDraw, ImageFont
    _FONT = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 18)
    _CJK = True
except Exception:
    _CJK = False


def _gstr(x):
    return "%.2f kg" % (x/1000.0) if x >= 1000 else "%d g" % x


_PCACHE = {"key": None}


def draw_panel(img, counts, areas=None):
    g = counts.get("green", 0); h = counts.get("half_ripened", 0); r = counts.get("fully_ripened", 0)
    _, wt_total, wt_ripe = estimate_yield(counts, areas)
    dis = [(n, counts[n]) for n in DISEASE_NAMES if counts.get(n, 0) > 0]
    HDR, GRN, RED, WHT = (255, 230, 0), (0, 255, 60), (255, 70, 70), (235, 235, 235)
    if _CJK:
        lines = [("产量估算", HDR),
                 (" 青果 %d    半熟 %d" % (g, h), WHT),
                 (" 红果(可采收) %d  ~%s" % (r, _gstr(wt_ripe)), RED),
                 (" 预计总产 ~%s" % _gstr(wt_total), GRN),
                 ("病害预警", HDR)]
        lines += [(" %s %d" % (CN.get(n, n), c), RED) for n, c in dis[:5]] or [(" 未发现病害", GRN)]
    else:
        lines = [("YIELD EST.", HDR),
                 (" Green %d   Half %d" % (g, h), WHT),
                 (" Ripe(harvest) %d  ~%s" % (r, _gstr(wt_ripe)), RED),
                 (" Proj.total ~%s" % _gstr(wt_total), GRN),
                 ("DISEASE ALERT", HDR)]
        lines += [(" %s %d" % (n, c), RED) for n, c in dis[:5]] or [(" none", GRN)]
    H, W = img.shape[:2]
    lh = 26 if _CJK else 22
    pw = 256
    ph = lh*len(lines) + 16
    x0, y0 = W - pw - 8, 8
    reg = img[y0:y0+ph, x0:x0+pw]
    reg[:] = reg // 2  # 半透明深色底,每帧廉价
    key = (g, h, r, tuple(dis), ph)
    if key != _PCACHE["key"]:  # 文字层仅计数变化时用 PIL 重绘(贵);平滑后大多帧命中缓存
        canvas = np.zeros((ph, pw, 3), np.uint8)
        if _CJK:
            pil = Image.fromarray(canvas)
            d = ImageDraw.Draw(pil)
            y = 6
            for txt, col in lines:
                d.text((10, y), txt, font=_FONT, fill=col)
                y += lh
            canvas = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        else:
            y = 20
            for txt, col in lines:
                cv2.putText(canvas, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (col[2], col[1], col[0]), 1, cv2.LINE_AA)
                y += lh
        _PCACHE.update(key=key, canvas=canvas, mask=canvas.max(axis=2) > 20)
    cvs, m = _PCACHE["canvas"], _PCACHE["mask"]
    rh, rw = reg.shape[:2]
    reg[m[:rh, :rw]] = cvs[:rh, :rw][m[:rh, :rw]]


def myFunc(rknn_lite, IMG):
    IMG2 = cv2.cvtColor(IMG, cv2.COLOR_BGR2RGB)
    # 等比例缩放
    IMG2, ratio, padding = letterbox(IMG2)
    # 强制放缩
    # IMG2 = cv2.resize(IMG, (IMG_SIZE, IMG_SIZE))
    IMG2 = np.expand_dims(IMG2, 0)

    outputs = rknn_lite.inference(inputs=[IMG2], data_format=['nhwc'])

    # print("oups1",len(outputs))
    # print("oups2",outputs[0].shape)

    boxes, classes, scores = yolov8_post_process(outputs)

    counts = {}
    area_sum = {}                       # 每类框面积和(px², 640输入空间), 供动态估重
    if boxes is not None:
        draw(IMG, boxes, scores, classes, ratio, padding)
        for box, c in zip(boxes, classes):
            nm = CLASSES[c]
            counts[nm] = counts.get(nm, 0) + 1
            area_sum[nm] = area_sum.get(nm, 0.0) + max(0.0, float((box[2] - box[0]) * (box[3] - box[1])))

    return IMG, counts, area_sum

