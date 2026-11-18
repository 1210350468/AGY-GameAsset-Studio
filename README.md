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

打开「资产制作」，输入资产名称、类型、描述，可以上传一张 PNG、JPG 或 WEBP 原画。上传原画时可直接制作 3D；使用描述时先经过 WAI 生成原画，再进入 3D 生成。

- **完整模型**：Pixal3D 生成几何与材质。
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

## Godot 4 导入

将资源包解压到 Godot 项目的 `res://assets/generated/<资产编号>/`，Godot 会自动导入 `model.glb`。资源包内已包含 `game_asset.tscn`，可以直接添加到游戏场景。静态资产使用盒形碰撞体，角色使用基础胶囊碰撞体。

### 结构检查与网格优化

资产库的 3D 预览支持材质、结构和网格显示模式，自动读取实际 GLB 的开放边界比例、连续网格比例、非流形连接、纹理和骨骼关节数量。质量报告接口为 `GET /api/jobs/{job_id}/inspect`，其中 `review_required` 表示需要进一步检查网格结构。

完整模型在 Blender 减面之前会合并重合的三维顶点，保留原有的 UV、材质和骨骼数据。复杂角色建议使用约 250000 个三角面进行高保真制作。资产库的「重新优化」操作会从原始生成模型重新制作 GLB 和 Godot 资源包，并保留已有原画，接口为 `POST /api/jobs/{job_id}/reprocess`。

WAI 原画生成按角色、怪物、武器和场景类别安排主体姿态与构图，优先采用单主体、清晰轮廓、纯色背景和柔和光照。重建与质量检查使用真实模型文件，资产库可以对比原画、材质、结构和网格。

### Anima 与 Qwen-Image 2.1 原画对照实验

为了测试多候选原画与多视角一致性，额外部署隔离的 ComfyUI 0.37.4。现有 WAI ComfyUI 0.29.2 与工作台 API 不受影响。

Anima 2.9B 使用完整精度的模型、Qwen3 0.6B 文本编码器与 Qwen-Image VAE；Qwen-Image 2.1 使用完整精度的图像模型、Qwen3-VL 8B 编码器与对应 VAE。原始权重放在 `asset-studio-data/models/nextgen`，通过软链接加载到独立 ComfyUI。

```bash
cd /data/xmu/ym/services/AGY-GameAsset-Studio
bash scripts/prepare-nextgen-comfy.sh
bash scripts/download-nextgen-models.sh all

# 只通过 CPU 检查真实 ComfyUI 的节点与权重注册
bash scripts/check-nextgen-nodes.sh
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model anima --validate --endpoint http://127.0.0.1:8191
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model qwen --validate --endpoint http://127.0.0.1:8191

# GPU1 空闲显存达到 50000 MiB 后启动独立推理服务
bash scripts/start-nextgen-comfy.sh
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model anima --output /data/xmu/ym/asset-studio-data/validation-assets/nextgen
/data/xmu/ym/asset-studio-data/envs/api/bin/python scripts/try-nextgen-models.py --model qwen --reference /data/xmu/ym/asset-studio-data/validation-assets/nextgen/anima/选定原画.png --output /data/xmu/ym/asset-studio-data/validation-assets/nextgen
```

Anima 生成四张同一主题的候选图，Qwen-Image 2.1 基于选定原画分别生成正面、左侧、背面和右侧参考。多视角图片用于评价外观一致性与单图重建输入的选择；当前 Pixal3D 工作台接口仍按一张输入图片执行三维重建。两套新工作流调用实际 ComfyUI 接口并读取生成的 PNG 文件。

GPU1 推理前通过 `nvidia-smi` 严格检查 50000 MiB 空闲显存条件，低于条件立即退出。科研训练进程保持原样，独立 GPU 推理服务位于 `127.0.0.1:8189`，CPU 节点检查服务位于 `127.0.0.1:8191`。

资源包包含模型、质量检查报告、资产元数据、原画（若提供）及可拆分部件（若有）。骨骼动画重定向、角色战斗状态机、技能逻辑和复杂装备穿模检查在游戏工程内完成。

## 验证

在 API 环境中运行代码测试：

```bash
python -m pip install -e '.[test]'
python -m pytest -q --basetemp ./data/pytest-run
python -m compileall -q asset_studio blender
```

AutoDL GPU 安装完成后执行真实生成验收，检查 `.glb` 通过 `trimesh` 与 `pygltflib` 解析，以及 `manifest.json` 的三角面数量、边界范围和 `skin` 状态。每个模型的实际生成时间、显存占用依赖 AutoDL GPU 型号和分辨率，需要在所租实例上记录。

