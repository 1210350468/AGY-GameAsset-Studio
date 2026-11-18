import argparse
import json
from pathlib import Path

from safetensors import safe_open


parser = argparse.ArgumentParser(description="检查 Anima 与 Qwen 的真实 safetensors 权重文件")
parser.add_argument("paths", nargs="+", type=Path)
args = parser.parse_args()

verified = []
for path in args.paths:
    absolute = path.resolve(strict=True)
    size = absolute.stat().st_size
    assert size > 100_000_000, f"模型文件大小异常：{absolute}"
    with safe_open(absolute, framework="pt", device="cpu") as weights:
        keys = list(weights.keys())
        assert len(keys) >= 10, f"模型权重参数数量异常：{absolute}"
        first = weights.get_slice(keys[0])
        verified.append({
            "file": str(absolute),
            "bytes": size,
            "tensor_count": len(keys),
            "first_tensor_name": keys[0],
            "first_tensor_shape": first.get_shape(),
            "first_tensor_dtype": first.get_dtype(),
        })

print(json.dumps(verified, ensure_ascii=False, indent=2))
