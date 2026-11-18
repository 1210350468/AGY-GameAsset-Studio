import os
import subprocess
import csv
import io

from asset_studio.settings import Settings


class GpuCapacityBusy(RuntimeError):
    pass


def choose_3d_gpu(settings: Settings, *, low_vram_pixal: bool = False) -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
        text=True, timeout=10,
    )
    rows = [
        (int(row[0].strip()), int(row[1].strip()), int(row[2].strip()))
        for row in csv.reader(io.StringIO(output)) if row
    ]
    # Pixal3D 官方 low_vram 模式分阶段加载模型，预留显存保护科研任务。
    required = 24000 if low_vram_pixal else max(50000, settings.min_free_gpu_mib)
    eligible = [row for row in rows if row[1] >= required]
    if not eligible:
        raise GpuCapacityBusy(f"等待 A800 空闲显存达到 {required} MiB，当前各卡空闲显存：{[row[1] for row in rows]}")
    selected = min(eligible, key=lambda item: (item[2], -item[1], item[0]))
    return selected[0]


def memory_headroom(settings: Settings) -> dict:
    if settings.min_free_gpu_mib == 0:
        return {"ready": True, "required_mib": 0}

    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",")[0].strip()
    result = subprocess.run(
        ["nvidia-smi", "-i", visible, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    free_mib = int(result.stdout.strip())
    return {
        "ready": free_mib >= settings.min_free_gpu_mib,
        "gpu": visible,
        "free_mib": free_mib,
        "required_mib": settings.min_free_gpu_mib,
    }


def require_gpu_headroom(settings: Settings) -> None:
    state = memory_headroom(settings)
    if not state["ready"]:
        raise RuntimeError(
            f"GPU {state['gpu']} 正在执行其他任务，当前空闲显存 "
            f"{state['free_mib']} MiB，资产生成需要至少 {state['required_mib']} MiB"
        )

