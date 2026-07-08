from rkllm.api import RKLLM

MODEL = '/root/models/Qwen2.5-0.5B-Instruct'
OUT = '/root/models/qwen2.5-0.5b-rv1126b-w8a8.rkllm'

llm = RKLLM()

ret = llm.load_huggingface(model=MODEL, model_lora=None, device='cpu')
assert ret == 0, f'load_huggingface failed: {ret}'

ret = llm.build(
    do_quantization=True,
    optimization_level=1,
    quantized_dtype='w8a8',
    quantized_algorithm='normal',
    target_platform='rv1126b',
    num_npu_core=1,
    max_context=2048,
)
assert ret == 0, f'build failed: {ret}'

ret = llm.export_rkllm(OUT)
assert ret == 0, f'export failed: {ret}'

print(f'OK -> {OUT}')
