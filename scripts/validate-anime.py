from pathlib import Path

from PIL import Image

from asset_studio.comfy import generate_image
from asset_studio.settings import Settings


settings = Settings.from_environment()
directory = settings.data_root / "validation-assets"
directory.mkdir(parents=True, exist_ok=True)
destination = directory / "wai-knight.png"

with (settings.data_root / "logs" / "anime-validation.log").open("a", encoding="utf-8") as log:
    generate_image(
        base_url=settings.comfy_url,
        checkpoint=settings.checkpoint,
        prompt="anime fantasy game character, ice knight, full body, intricate blue armor, magic sword",
        destination=destination,
        seed=314159,
        steps=24,
        timeout_seconds=1200,
        log=log,
    )

with Image.open(destination) as output:
    output.verify()
with Image.open(destination) as output:
    assert output.size == (1024, 1024), f"生成图片尺寸异常：{output.size}"

print(f"PASS: {destination}, {destination.stat().st_size} bytes")
