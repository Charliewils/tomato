import sys, time
import numpy as np
sys.path.insert(0, "/root/demo")
from rknnpool.rknnpool_ld import rknnPoolExecutor
from func.func_yolov8_optimize import myFunc

pool = rknnPoolExecutor("./rknnModel/best.rknn", 8, myFunc)
img = (np.random.rand(640, 640, 3) * 255).astype(np.uint8)
for _ in range(8):
    pool.put(img)
t0 = time.time(); n = 0
while time.time() - t0 < 30:
    pool.put(img)
    r, f = pool.get()
    if not f:
        break
    n += 1
    if n % 50 == 0:
        print("det frames %d  fps %.1f" % (n, n / (time.time() - t0)), flush=True)
pool.release()
print("det done frames=%d" % n, flush=True)
