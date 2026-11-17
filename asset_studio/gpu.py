import os
import subprocess

from asset_studio.settings import Settings


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

