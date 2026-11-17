import os
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path
    data_root: Path
    comfy_url: str
    checkpoint: str
    pixal_low_vram: bool
    blender: str
    timeout_seconds: int
    min_free_gpu_mib: int = 0
    godot: str = "godot"

    @classmethod
    def from_environment(cls) -> "Settings":
        root = PROJECT_ROOT
        data_root = Path(os.environ.get("ASSET_STUDIO_DATA_ROOT", str(root / "data"))).resolve()
        return cls(
            root=root,
            data_root=data_root,
            comfy_url=os.environ.get("ASSET_STUDIO_COMFY_URL", "http://127.0.0.1:8188").rstrip("/"),
            checkpoint=os.environ.get("ASSET_STUDIO_IMAGE_CHECKPOINT", "waiIllustriousSDXL_v170.safetensors"),
            pixal_low_vram=os.environ.get("ASSET_STUDIO_PIXAL_LOW_VRAM", "1") == "1",
            blender=os.environ.get("ASSET_STUDIO_BLENDER", "blender"),
            timeout_seconds=int(os.environ.get("ASSET_STUDIO_TIMEOUT_SECONDS", "7200")),
            min_free_gpu_mib=int(os.environ.get("ASSET_STUDIO_MIN_GPU_FREE_MIB", "0")),
            godot=os.environ.get("ASSET_STUDIO_GODOT", "godot"),
        )

    @property
    def jobs_root(self) -> Path:
        return self.data_root / "jobs"

    @property
    def sources(self) -> Path:
        return self.data_root / "sources"

    @property
    def envs(self) -> Path:
        return self.data_root / "envs"

    @property
    def image_checkpoint(self) -> Path:
        return self.sources / "ComfyUI-v0.29.2" / "models" / "checkpoints" / self.checkpoint

    @property
    def pixal_repo(self) -> Path:
        return self.sources / "Pixal3D"

    @property
    def pixal_model_path(self) -> Path:
        return Path(os.environ.get(
            "ASSET_STUDIO_PIXAL_MODEL_ROOT", str(self.data_root / "models" / "Pixal3D")
        )).resolve()

    @property
    def part_repo(self) -> Path:
        return self.sources / "PartCrafter"

    @property
    def rig_repo(self) -> Path:
        return self.sources / "SkinTokens"

    @property
    def pixal_python(self) -> Path:
        return self.envs / "pixal" / "bin" / "python"

    @property
    def part_python(self) -> Path:
        return self.envs / "parts" / "bin" / "python"

    @property
    def rig_python(self) -> Path:
        return self.envs / "rig" / "bin" / "python"

    def blender_binary(self) -> str | None:
        path = Path(self.blender)
        return str(path) if path.is_file() else shutil.which(self.blender)

    def godot_binary(self) -> str | None:
        configured = Path(self.godot)
        if configured.is_file():
            return str(configured)
        installed = self.data_root / "tools" / "godot-4.7.2" / "Godot_v4.7.2-stable_linux.x86_64"
        if installed.is_file():
            return str(installed)
        return shutil.which(self.godot)

    def prepare_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)

