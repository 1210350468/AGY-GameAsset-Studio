# AGY 游戏资产工作台

中文游戏资产生产工作台，部署在 xmu21 A800 或 AutoDL GPU 实例中，供浏览器和 AGY 通过统一 HTTP API 提交任务。采用一套二次元图像模型、主力 3D 模型、可拆分部件模型、自动骨骼模型和 Blender，实现从原画到 Godot 资源包的制作流程。

## xmu21 A800 现用部署

项目目录：`/data/xmu/ym/services/AGY-GameAsset-Studio`，模型、环境、数据与日志目录：`/data/xmu/ym/asset-studio-data`。

在已经配置 `xmu21-a800` SSH 别名的 Windows 计算机上，可以运行以下工作台自动连接脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows/Install-AGY-Skill.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File windows/Register-XMU21-Asset-Studio.ps1
```

它会注册每分钟运行的 Windows 计划任务，自动建立 `127.0.0.1:18333` 到 xmu21 的 SSH 隧道，并在连接中断后重新连接。原先指向 xmu85 的计划任务应保持禁用。

xmu21 上的二次元原画服务使用 ComfyUI v0.29.2，兼容已验证的 PyTorch 2.6.0 CUDA 环境。安装脚本会复用此前下载的 WAI Illustrious v17 权重。
Pixal3D 的单视图与多视图权重统一保存至 `asset-studio-data/models/Pixal3D`，DINOv3、MoGe-2、BiRefNet 和 NAF 辅助权重分别保存在 Hugging Face 缓存和 Torch Hub 缓存中。Pixal3D 使用 `config/pixal-pipeline.json` 配置模型组合。PartCrafter 和 SkinTokens 的权重保存在各自的源码目录中。

xmu21 使用以下配置安装：

```bash
cd /data/xmu/ym/services/AGY-GameAsset-Studio
cp .env.xmu21.example .env
bash scripts/install-blender.sh
bash scripts/install-godot.sh
bash scripts/download-models.sh all
bash scripts/install-autodl.sh all
bash scripts/start.sh
```

服务器中已经配置 CUDA 12.4 和 `uv`，不需要 sudo 权限即可建立 Python 环境。所有模型源码通过 GitHub 官方归档包安装，减少 Git 传输长时间挂起的问题。`HF_ENDPOINT` 指向 Hugging Face 镜像。

为了保护同时执行的科研任务，xmu21 配置会在所选 GPU 空闲显存达到 50,000 MiB 后允许新的模型推理；这个限制对已有 GLB 文件的 Blender 优化与导出没有影响。

## 模型与工具

| 阶段 | 工具 | 职责 |
| --- | --- | --- |
| 二次元原画 | WAI-NSFW-Illustrious XL v17 + ComfyUI | 自由生成二次元角色、怪物、装备原画 |
| 完整 3D 模型 | TencentARC Pixal3D（TRELLIS.2 架构） | 从参考图片重建几何与材质 |
| 部件模型 | wgsxm PartCrafter | 从参考图生成多个独立部件及组合 GLB |
| 骨骼蒙皮 | VAST-AI-Research SkinTokens | 为角色、怪物生成骨骼和蒙皮权重 |
| 模型加工 | Blender | 减面、UV、统一 GLB 导出 |
| 游戏资源 | Godot 4 | GLB 资源导入、碰撞体、场景实例 |

## AutoDL 部署

推荐 NVIDIA RTX 4090 24GB，Ubuntu Linux、Conda、CUDA Toolkit 12.4 或匹配的更新版本，以及至少 100GB 可用数据盘。预留更多空间存放多个模型权重和生成资产。不同模型使用独立 Python 环境，单队列顺序调用 GPU。

在 AutoDL 终端执行：

```bash
git clone https://github.com/1210350468/AGY-GameAsset-Studio.git
cd AGY-GameAsset-Studio
cp .env.example .env
bash scripts/download-models.sh all
bash scripts/install-autodl.sh all
bash scripts/start.sh
```

部署脚本默认把权重、Python 环境、源码副本和生成资产存储在 `/root/autodl-tmp/agy-game-asset-studio`。源代码仓库与大模型文件分开管理。模型权重从 Hugging Face 下载，首次生成时部分模型还会下载额外依赖权重。

也可以按照顺序单独安装模块并检查日志：

```bash
bash scripts/install-autodl.sh api
bash scripts/install-autodl.sh anime
bash scripts/install-autodl.sh pixal3d
bash scripts/install-autodl.sh partcrafter
bash scripts/install-autodl.sh skintokens
bash scripts/install-autodl.sh godot
bash scripts/doctor.sh
bash scripts/start.sh
```

AutoDL 登录后需确认 `nvidia-smi`、`nvcc --version`、`conda` 均可正常执行。Pixal3D 依赖多个 CUDA 扩展，安装过程中会进行源码编译。SkinTokens 官方推荐 Python 3.11、CUDA 12.1+ 及至少 14GB 显存。

## Windows 浏览器访问

工作台默认监听 AutoDL 容器内 `127.0.0.1:18333`。在 Windows PowerShell 建立 SSH 端口转发：

```powershell
ssh -N -L 127.0.0.1:18333:127.0.0.1:18333 -p <AutoDL-SSH端口> root@<AutoDL-SSH主机>
```

然后访问：

- 工作台：[http://127.0.0.1:18333/](http://127.0.0.1:18333/)
- OpenAPI：[http://127.0.0.1:18333/docs](http://127.0.0.1:18333/docs)
- API 健康检查：`GET /health`
- 模型安装与 GPU 状态：`GET /api/system`
- GPU 和基础模型安装检查：`GET /ready`

通过 SSH 隧道访问，无需将服务暴露到公网。AutoDL 用户也可以按照官方自定义服务文档配置对外映射端口及网络访问控制。

## 工作台操作

打开「资产制作」，输入资产名称、类型、描述，可以上传一张 PNG、JPG 或 WEBP 原画。通过「原画生成模型」下拉栏选择 Qwen-Image 2.1、Anima 2.9B 或 WAI Illustrious v17；配置了 `OPENAI_API_KEY` 后还可选择 GPT Image 2.5 Flare。候选数量支持 1 张或 4 张。上传原画会直接开始建模，勾选「Qwen 四视角增强建模」可生成并使用多角度参考。

- **完整模型**：Pixal3D 生成几何与材质。
- **多视角完整模型**：Qwen 为选定主原画生成正面、右侧、背面、左侧四张参考图；使用 Pixal3D 的 `inference_mv.py` 与 `pipeline_mv.json` 多视角权重，并将实际参考图与相机参数保存在任务目录。
- **可拆分部件**：PartCrafter 生成多个独立 GLB 及组合模型。
- **自动骨骼**：角色与怪物使用 SkinTokens，输入角色和复杂异形时仍需要检查骨骼效果。
- **Blender**：统一执行减面处理，保留模型骨骼与材质，生成缺失的 UV 并导出 GLB。
- **Godot 4.7.2**：通过无界面引擎实际导入 GLB，创建含碰撞体的 `game_asset.tscn`，并验证生成的场景能够重新加载。
- **资产库**：展示成功模型，下载 GLB 和包含元数据的 Godot 资源包。

所有步骤保留真实进度状态与子进程日志。角色生成包记录是否存在骨骼和动画。独立动作生成、动画重定向及武器挂点编辑属于后续 Godot 游戏侧流程，需要结合实际角色动作制作。

## AGY API

### 描述生成角色

```bash
curl -X POST http://127.0.0.1:18333/api/jobs \
  -F 'title=冰霜骑士' \
  -F 'kind=character' \
  -F 'mode=whole' \
  -F 'image_model=qwen' \
  -F 'image_count=4' \
  -F 'multi_views=true' \
  -F 'prompt=anime fantasy hero, full body, silver and blue armor, ice sword' \
  -F 'rig=true'
```

### 使用参考图生成

```bash
curl -X POST http://127.0.0.1:18333/api/jobs \
  -F 'title=冰霜怪物' -F 'kind=monster' -F 'mode=parts' \
  -F 'num_parts=4' -F 'image=@character.png'
```

### 直接处理已有 GLB

```bash
curl -X POST http://127.0.0.1:18333/api/import \
  -F 'title=遗迹石柱' -F 'kind=prop' -F 'file=@column.glb'
```

查询任务：`GET /api/jobs/{job_id}`；读取日志：`GET /api/jobs/{job_id}/log`；下载完整资源包：`GET /api/jobs/{job_id}/file/godot_asset.zip`；下载 GLB：`GET /api/jobs/{job_id}/file/model.glb`；下载场景：`GET /api/jobs/{job_id}/file/game_asset.tscn`。

原画模型选项与是否已配置：`GET /api/config`；查看任务的候选原画及多角度参考：`GET /api/jobs/{job_id}/references`；使用已生成的 Qwen 四视角重新建模：`POST /api/nextgen/build`。四视角输入统一转成正方形 RGB 图片，处理近乎全不透明的 Alpha，规范主体尺寸。相机矩阵来自 Pixal3D 官方示例，`preflight.json` 记录每张图片的来源、尺寸、透明度和相机角度假设。Qwen 编辑视角的精确相机姿态需要经过几何重建对照评估。

Pixal3D 的四视角重建使用 `pipeline_mv_cached_birefnet.json`，沿用 Pixal3D 官方单图配置已经支持的 `ZhengPeng7/BiRefNet` 抠图模型。安装过程会将此配置安装到 Pixal3D 权重目录。对已下载齐全的模型，推理时通过 Hugging Face 离线模式读取本地权重。

## Godot 4 导入

将资源包解压到 Godot 项目的 `res://assets/generated/<资产编号>/`，Godot 会自动导入 `model.glb`。资源包内已包含 `game_asset.tscn`，可以直接添加到游戏场景。静态资产使用盒形碰撞体，角色使用基础胶囊碰撞体。

### 结构检查与网格优化

资产库的 3D 预览支持材质、结构和网格显示模式，自动读取实际 GLB 的开放边界比例、连续网格比例、非流形连接、纹理和骨骼关节数量。质量报告接口为 `GET /api/jobs/{job_id}/inspect`，其中 `review_required` 表示需要进一步检查网格结构。

当完整 GLB 超过 8 MB，工作台使用 glTF Transform 4.5.0 处理贴图最长边为 1024 像素，并通过 Meshopt 压缩生成浏览器专用 `preview.glb`。三角网格结构经过实际数据检查后保持一致，工作台通过 Three.js MeshoptDecoder 读取预览。完整分辨率的 `model.glb` 与 Godot 资源包保留原始几何，可通过 `GET /api/jobs/{job_id}/file/preview.glb` 获取预览文件。

Pixal3D 完整模型保留原始 GLB 几何与 UV，避免重新导入 Blender 造成的拓扑与面朝向变化。原始模型、最终游戏模型与浏览器预览中间文件分别检查最大连续网格、开放边界、非流形边、面朝向与贴图。未通过检查的模型停止游戏资源包制作，同时保存 `raw_quality.json` 等真实诊断数据。模型重建与检查依赖实际权重和实际文件。

### Pixal3D 视角输入与几何对照

```bash
cd /data/xmu/ym/services/AGY-GameAsset-Studio
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/compare-pixal-views.py \
  --data-root /data/xmu/ym/asset-studio-data \
  --source-views /data/xmu/ym/asset-studio-data/jobs/来源任务编号/views \
  --output /data/xmu/ym/asset-studio-data/validation-assets/pixal-input-fix-20261119 \
  --modes single front-back four
```

单图运行官方 `inference.py`；前后双图与四图运行官方 `inference_mv.py`，每种情况分别生成独立的相机文件、原始 GLB 和质量报告。实际结果通过 `GET /api/nextgen/experiments` 读取，也可以在 `/nextgen` 页面查看。只有几何质量合格的模型可以通过 `POST /api/nextgen/experiments/{mode}/package` 进入 Godot 资源制作。

同一组 Qwen 原画的实测：单图最大连续比例 98.05%、非流形边 6619 条；前后双图分别为 98.01%、4047 条；四图分别为 97.30%、7951 条。当前自动验收要求最大连续比例至少 97%，非流形边比例不超过 0.35%，开放边界比例不超过 0.5%，并检查面朝向一致性。前后双视角的结构指标符合本次要求。多视角条件中的相机姿态为未经过几何标定的生成视角假设，继续在预处理报告中显式记录。

完整安装时使用 `bash scripts/install-autodl.sh gltf-transform` 安装隔离的 Node.js 22.15 与 glTF Transform 4.5.0，用于保持网格连续性的浏览器压缩预览。

WAI 原画生成按角色、怪物、武器和场景类别安排主体姿态与构图，优先采用单主体、清晰轮廓、纯色背景和柔和光照。重建与质量检查使用真实模型文件，资产库可以对比原画、材质、结构和网格。

### Anima 与 Qwen-Image 2.1 原画对照实验

为了测试多候选原画与多视角一致性，额外部署隔离的 ComfyUI 0.37.4。现有 WAI ComfyUI 0.29.2 与工作台 API 不受影响。

Anima 2.9B 使用完整精度的模型、Qwen3 0.6B 文本编码器与 Qwen-Image VAE；Qwen-Image 2.1 使用完整精度的图像模型、Qwen3-VL 8B 编码器与对应 VAE。原始权重放在 `asset-studio-data/models/nextgen`，通过软链接加载到独立 ComfyUI。

```bash
cd /data/xmu/ym/services/AGY-GameAsset-Studio
bash scripts/prepare-nextgen-comfy.sh
bash scripts/download-nextgen-models.sh all

# 无 GPU 推理时检查真实源码中的 Anima 与 Qwen 节点定义
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/verify-nextgen-source.py --source /data/xmu/ym/asset-studio-data/sources/ComfyUI-v0.37.4
/data/xmu/ym/asset-studio-data/envs/anime_next/bin/python scripts/verify-nextgen-weights.py /data/xmu/ym/asset-studio-data/models/nextgen/Anima-2.9B/Anima-2.9B-preview-v1.safetensors

# 根据全部 A800 的空闲显存与计算负载自动选择显卡，分别运行独立服务
bash scripts/start-nextgen-comfy.sh anima
bash scripts/start-nextgen-comfy.sh qwen
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model anima --validate
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model qwen --validate
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model anima --output /data/xmu/ym/asset-studio-data/validation-assets/nextgen
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model qwen --reference /data/xmu/ym/asset-studio-data/validation-assets/nextgen/anima/选定原画.png --output /data/xmu/ym/asset-studio-data/validation-assets/nextgen
```

Anima 生成四张同一主题的候选图，Qwen-Image 2.1 基于选定原画分别生成正面、左侧、背面和右侧参考。工作台现已提供单图建模与 Pixal3D 多视角重建，所有输入与输出均保存为真实文件。

生成的候选图片与多视角参考可以在 [多视角实验画廊](http://127.0.0.1:18333/nextgen) 中查看，也能通过 `GET /api/nextgen/previews` 获取真实文件列表。画廊直接读取已验证的 PNG 文件，页面在现有 Windows SSH 隧道上访问。

每次启动会检查全部 GPU 的空闲显存与利用率，分别为 Anima、Qwen-Image 2.1 预留 18000 MiB、32000 MiB 推理预算，并保留 8000 MiB 显存余量。两个 ComfyUI 服务分别监听 `127.0.0.1:8189` 和 `127.0.0.1:8190`，自动选择独立 GPU，分别保存用户目录、数据库、输入和输出文件。推理期间使用模型卸载与 CPU VAE 降低显存压力；重复生成参考图时会直接复用已完成且通过 PNG 验证的视角文件。科研训练进程保持原样，实际 ComfyUI `/object_info` 节点注册检查安排在 GPU 服务启动后执行。

资源包包含模型、质量检查报告、资产元数据、原画（若提供）及可拆分部件（若有）。骨骼动画重定向、角色战斗状态机、技能逻辑和复杂装备穿模检查在游戏工程内完成。

## 验证

在 API 环境中运行代码测试：

```bash
python -m pip install -e '.[test]'
python -m pytest -q --basetemp ./data/pytest-run
python -m compileall -q asset_studio blender
```

AutoDL GPU 安装完成后执行真实生成验收，检查 `.glb` 通过 `trimesh` 与 `pygltflib` 解析，以及 `manifest.json` 的三角面数量、边界范围和 `skin` 状态。每个模型的实际生成时间、显存占用依赖 AutoDL GPU 型号和分辨率，需要在所租实例上记录。

