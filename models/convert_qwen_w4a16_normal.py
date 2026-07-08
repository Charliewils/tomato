import os
from rkllm.api import RKLLM

HERE = os.path.dirname(os.path.abspath(__file__))
MODELPATH = os.path.expanduser('~/models/Qwen2.5-0.5B-Instruct')
OUT = os.path.expanduser('~/models/qwen2.5-0.5b-rv1126b-w4a16.rkllm')

llm = RKLLM()
ret = llm.load_huggingface(model=MODELPATH, model_lora=None, device='cpu',
                           dtype='float32', custom_config=None, load_weight=True)
assert ret == 0, f'load failed {ret}'

ret = llm.build(do_quantization=True, optimization_level=1,
                quantized_dtype='w4a16', quantized_algorithm='normal',
                target_platform='RV1126B', num_npu_core=1,
                extra_qparams=None,
                dataset='/mnt/d/rknn-llm/_rv1126b/data_quant.json',
                hybrid_rate=0, max_context=2048)
assert ret == 0, f'build failed {ret}'

ret = llm.export_rkllm(OUT)
assert ret == 0, f'export failed {ret}'
print('EXPORT_OK', OUT, 'size_MB', round(os.path.getsize(OUT)/1e6, 1))
