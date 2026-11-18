import argparse
import sys

from asset_studio.nextgen import GPU_MEMORY_REQUIREMENTS, GPU_MEMORY_RESERVE_MIB, select_gpu


parser = argparse.ArgumentParser(description="为游戏资产生成自动选择可用 A800")
parser.add_argument("--model", choices=sorted(GPU_MEMORY_REQUIREMENTS), required=True)
parser.add_argument("--exclude", type=int, action="append", default=[])
args = parser.parse_args()

selected = select_gpu(args.model, set(args.exclude))
print(
    f"{args.model} 选择 GPU{selected['index']}：空闲 {selected['free_mib']} MiB，"
    f"使用率 {selected['utilization']}%，推理预算 {GPU_MEMORY_REQUIREMENTS[args.model]} MiB，"
    f"预留 {GPU_MEMORY_RESERVE_MIB} MiB",
    file=sys.stderr,
)
print(selected["index"])
