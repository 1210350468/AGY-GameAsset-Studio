---
name: game-asset-studio
description: "使用 xmu21 A800 游戏资产工作台，根据二次元原画或描述生成角色、怪物、武器、装备和场景 GLB，进行部件建模、骨骼蒙皮、Blender 优化与 Godot 资源包导出。支持自动提交、查询任务、查看日志和读取质量报告。"
---

# AGY 游戏资产工作台

## 服务与检查

Windows 用户使用 `http://127.0.0.1:18333` 访问 xmu21 上的工作台。

- 中文工作台：`GET /`
- API 健康状态：`GET /health`
- 模型安装、GPU 占用和驱动状态：`GET /api/system`
- GPU 生成就绪检查：`GET /ready`
- 创建任务：`POST /api/jobs`，使用 `multipart/form-data`
- 全部任务：`GET /api/jobs`
- 任务详情：`GET /api/jobs/{job_id}`
- 任务运行日志：`GET /api/jobs/{job_id}/log`
- 资产库：`GET /api/assets`
- 下载 GLB：`GET /api/jobs/{job_id}/file/model.glb`
- 下载资源包：`GET /api/jobs/{job_id}/file/godot_asset.zip`
- 读取真实模型质量：`GET /api/jobs/{job_id}/file/quality.json`

连接异常时，在 Windows 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.gemini\config\skills\game-asset-studio\Start-XMU21-Asset-Studio.ps1"
```

Windows 计划任务 `AGY Game Asset Studio Tunnel` 每 30 秒检查连接并自动重新建立 SSH 隧道。

## 生成模式

`kind`：`character`、`monster`、`weapon`、`equipment`、`prop`、`scene`。

`mode=whole` 运行 Pixal3D，生成完整几何和材质；`mode=parts` 运行 PartCrafter，生成可分开的三维部件。`rig=true` 对角色和怪物运行 SkinTokens，生成骨骼及蒙皮。

输入图片时直接进入 3D 建模，提交文字描述时使用 WAI Illustrious v17 创建原画。系统自动执行 Blender 网格加工和 GLB 质量检查。

Windows PowerShell 示例：

```powershell
curl.exe -fsS -X POST 'http://127.0.0.1:18333/api/jobs' `
  -F 'title=冰霜战士' `
  -F 'kind=character' `
  -F 'mode=whole' `
  -F 'prompt=anime fantasy knight, full body, blue armor, rune sword' `
  -F 'rig=true'
```

使用现有原画：

```powershell
curl.exe -fsS -X POST 'http://127.0.0.1:18333/api/jobs' `
  -F 'title=地牢怪物' `
  -F 'kind=monster' `
  -F 'mode=parts' `
  -F 'num_parts=4' `
  -F 'image=@C:\path\to\monster.png'
```

已有 GLB 的模型优化：

```powershell
curl.exe -fsS -X POST 'http://127.0.0.1:18333/api/import' `
  -F 'title=地牢石柱' -F 'kind=prop' `
  -F 'file=@C:\path\to\column.glb'
```

## 任务处理要求

提交之前读取 `/api/system`，确认所需模型 `installed=true`、CUDA 驱动可用和 GPU 空闲显存达到服务端要求。科研任务占用 GPU 时，工作台保留任务日志并报告服务器资源状态。

创建成功会返回 `job_id`。使用 `GET /api/jobs/{job_id}` 查询当前状态和处理阶段。只有 `status=completed` 才能报告资产制作完成；下载 `quality.json` 与 `manifest.json` 检查实际几何、边界、三角面和骨骼。文件下载必须验证 HTTP 状态码和有效文件长度。

生成的 Godot 资源包包括 `model.glb`、`quality.json`、`manifest.json`、原画及拆分部件。角色的动作状态机、装备挂点和战斗逻辑应根据实际游戏工程进一步配置。

