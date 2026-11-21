import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

const $ = (selector) => document.querySelector(selector);
const pages = {create: "制作游戏资产", jobs: "任务进度", assets: "资产库", system: "模型与设备"};
const types = {character: "角色", monster: "怪物", weapon: "武器", equipment: "装备", prop: "道具", scene: "场景"};
const imageModels = {qwen: "Qwen-Image 2.1", anima: "Anima 2.9B", wai: "WAI Illustrious v17", "gpt-image": "GPT Image 2.5 Flare"};
let currentPage = "create";
let viewer = null;
let notificationTimer = null;
let assetCache = [];
let assetsSignature = "";
let jobFilter = "all";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail ?? `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function notify(message, timeout = 5500) {
  const element = $("#notification");
  element.textContent = message;
  element.hidden = false;
  clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => { element.hidden = true; }, timeout);
}

function navigate(page) {
  currentPage = page;
  $("#page-title").textContent = pages[page];
  document.querySelectorAll(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.view === page));
  document.querySelectorAll(".view").forEach((element) => element.classList.toggle("active", element.id === `view-${page}`));
  if (page === "jobs") refreshJobs();
  if (page === "assets") refreshAssets();
  if (page === "system") refreshSystem();
  if (page !== "assets") closeViewer();
}

document.querySelectorAll(".nav-item").forEach((element) => element.addEventListener("click", () => navigate(element.dataset.view)));

document.querySelectorAll(".type-choice").forEach((element) => element.addEventListener("click", () => {
  document.querySelectorAll(".type-choice").forEach((choice) => choice.classList.remove("selected"));
  element.classList.add("selected");
  $("#asset-kind").value = element.dataset.kind;
  const canRig = ["character", "monster"].includes(element.dataset.kind);
  $("#rig").disabled = !canRig;
  $("#rig").checked = canRig;
  $("#target-faces").value = canRig ? "250000" : "50000";
  $("#face-guidance").textContent = canRig
    ? "复杂角色保留约 25 万个三角面，以减少极端减面产生的网格破碎。生成后会检查真实结构。"
    : "静态道具默认以 5 万个三角面为目标，生成后会检查真实结构。";
}));

$("#asset-image").addEventListener("change", (event) => {
  const file = event.target.files[0];
  $("#upload-text").textContent = file ? file.name : "选择角色原画、装备图片或怪物设定图";
  $("#image-preview-wrap").hidden = !file;
  if (file) $("#image-preview").src = URL.createObjectURL(file);
  syncImageSelection();
});
$("#clear-image").addEventListener("click", () => {
  $("#asset-image").value = "";
  $("#image-preview").removeAttribute("src");
  $("#image-preview-wrap").hidden = true;
  $("#upload-text").textContent = "选择角色原画、装备图片或怪物设定图";
  syncImageSelection();
});

function syncImageSelection() {
  const uploaded = Boolean($("#asset-image").files.length);
  $("#image-model").disabled = uploaded;
  $("#image-count").disabled = uploaded;
  $("#image-model-notice").textContent = uploaded
    ? "已选择参考图片，直接使用上传原画进行三维建模；可以开启正反双视角增强。"
    : "原画模型决定实际调用的生成服务。四张候选会全部保存，默认使用第一张建模。";
}

$("#model-mode").addEventListener("change", () => {
  if ($("#model-mode").value === "parts") {
    $("#multi-views").checked = false;
    $("#quality-target").value = "prototype";
  }
  $("#multi-views").disabled = $("#model-mode").value === "parts";
  syncMultiViewInputs();
});

$("#quality-target").addEventListener("change", () => {
  if ($("#quality-target").value === "production") {
    $("#model-mode").value = "whole";
    $("#multi-views").disabled = false;
    $("#multi-views").checked = true;
    $("#multi-view-strategy").value = "four";
  }
  syncMultiViewInputs();
});

function syncMultiViewInputs() {
  const enabled = $("#multi-views").checked && $("#model-mode").value === "whole";
  const four = $("#multi-view-strategy").value === "four";
  $("#multiview-options").hidden = !enabled;
  $("#multi-view-strategy").disabled = !enabled;
  $("#view-back").disabled = !enabled;
  $("#multiview-side-views").hidden = !enabled || !four;
  $("#view-right").disabled = !enabled || !four;
  $("#view-left").disabled = !enabled || !four;
}

$("#multi-views").addEventListener("change", syncMultiViewInputs);
$("#multi-view-strategy").addEventListener("change", syncMultiViewInputs);
syncMultiViewInputs();

api("/api/config").then((settings) => {
  for (const model of settings.image_models) {
    const option = $("#image-model").querySelector(`option[value="${model.id}"]`);
    if (option) {
      option.disabled = !model.available;
      option.textContent = `${imageModels[model.id]}${model.available ? "" : " · 尚未配置"}`;
    }
  }
  const preferred = settings.image_models.find((model) => model.id === "qwen" && model.available)
    || settings.image_models.find((model) => model.available);
  if (preferred) $("#image-model").value = preferred.id;
  if (!settings.pixal_multiview_ready) {
    $("#multi-views").disabled = true;
    $("#multi-views").checked = false;
    syncMultiViewInputs();
  }
  syncImageSelection();
}).catch((error) => { $("#image-model-notice").textContent = `无法读取模型状态：${error.message}`; });

$("#build-sample-views").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const response = await api("/api/nextgen/build", {method: "POST", body: new FormData()});
    notify(`Qwen 四视角建模任务已登记：${response.job_id.slice(0, 8)}`);
    navigate("jobs");
  } catch (error) {
    notify(`四视角任务提交失败：${error.message}`, 11000);
  } finally {
    button.disabled = false;
  }
});

$("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("#quality-target").value === "production") {
    const uploadIds = ["asset-image", "view-right", "view-back", "view-left"];
    if (
      $("#model-mode").value !== "whole" ||
      !$("#multi-views").checked ||
      $("#multi-view-strategy").value !== "four" ||
      uploadIds.some((name) => !document.getElementById(name).files.length)
    ) {
      notify("赛季游戏资产需要同一角色的正面、右面、背面和左面四张实际参考图，请上传对应图片。", 11000);
      return;
    }
  }
  const button = $("#submit-job");
  const form = new FormData(event.target);
  if (!$("#asset-image").files.length) form.delete("image");
  button.disabled = true;
  button.textContent = "正在提交…";
  try {
    const response = await api("/api/jobs", {method: "POST", body: form});
    notify(`任务 ${response.job_id.slice(0, 8)} 已进入队列`);
    navigate("jobs");
  } catch (error) {
    notify(`提交失败：${error.message}`, 11000);
  } finally {
    button.disabled = false;
    button.textContent = "✦  开始制作资产";
  }
});

$("#import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const response = await api("/api/import", {method: "POST", body: new FormData(event.target)});
    notify(`已导入 GLB，任务 ${response.job_id.slice(0, 8)} 已开始`);
    navigate("jobs");
  } catch (error) {
    notify(`导入失败：${error.message}`, 11000);
  } finally {
    button.disabled = false;
  }
});

async function refreshJobs() {
  const data = await api("/api/jobs?limit=100");
  const activeCount = data.jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  const completedCount = data.jobs.filter((job) => job.status === "completed").length;
  const reviewCount = data.jobs.filter((job) => job.status === "review_required").length;
  const failedCount = data.jobs.filter((job) => job.status === "failed").length;
  $("#job-count").textContent = activeCount;
  if (currentPage !== "jobs") return;
  $("#job-summary").innerHTML = `<div><small>队列与进行中</small><strong>${activeCount}</strong></div><div><small>已完成的资产</small><strong>${completedCount}</strong></div><div><small>等待外观审核</small><strong>${reviewCount}</strong></div><div><small>异常任务</small><strong>${failedCount}</strong></div>`;
  const filtered = data.jobs.filter((job) => jobFilter === "all" || (jobFilter === "active" ? ["queued", "running"].includes(job.status) : job.status === jobFilter));
  $("#job-list").innerHTML = filtered.length ? filtered.map((job) => {
    const status = {queued: "等待处理", running: "正在制作", completed: "已完成", review_required: "等待外观审核", rejected: "外观不合格", failed: "失败"}[job.status] ?? job.status;
    const fileUrl = `/api/jobs/${job.id}/file/`;
    return `<article class="job-card">
      <div class="job-head"><strong>${escapeHtml(job.title)}</strong><span class="label-state ${escapeHtml(job.status)}">${status}</span></div>
      <div class="job-meta">${escapeHtml(types[job.kind] || job.kind)} · ${job.params?.quality_target === "production" ? "四视角游戏候选" : "原画实验或历史任务"} · ${job.mode === "whole" ? "完整模型" : job.mode === "parts" ? "拆分部件" : "GLB 优化"} · ${escapeHtml(imageModels[job.params?.image_model] || "已有原画")} · ${escapeHtml(job.stage)} · ${escapeHtml(job.created_at.slice(0, 19).replace("T", " "))}</div>
      ${job.has_preview ? `<a class="job-concept-link" href="${fileUrl}input.png" target="_blank" rel="noopener noreferrer"><img src="${fileUrl}input.png" alt="${escapeHtml(job.title)} 原画" loading="lazy"></a>` : ""}
      <div class="progress-track"><div style="width:${Math.round(job.progress * 100)}%"></div></div>
      ${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ""}
      <div class="job-actions"><button class="link-btn" data-log="${job.id}">查看日志</button>
      ${["completed", "review_required", "rejected"].includes(job.status) ? `<a class="link-btn" href="${fileUrl}model.glb">下载 GLB</a><a class="link-btn" href="${fileUrl}godot_asset.zip">下载 Godot 资源包</a><a class="link-btn" href="/?asset=${job.id}">3D 预览</a>` : ""}
      ${job.status === "review_required" ? `<button class="link-btn" data-review-action="approve" data-review-id="${job.id}">外观合格</button><button class="link-btn" data-review-action="reject" data-review-id="${job.id}">外观不合格</button>` : ""}
      ${["completed", "review_required", "rejected"].includes(job.status) && ["character", "monster"].includes(job.kind) ? `<button class="link-btn" data-texture-repair="${job.id}">修复黑色贴图残留</button>` : ""}
      ${job.params?.multi_views ? `<a class="link-btn" href="/api/jobs/${job.id}/references" target="_blank">多视角参考</a>` : ""}
      ${job.kind === "monster" && job.has_preview && ["completed", "failed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-repair-ground="${job.id}">清理怪物脚底地面并重建</button>` : ""}
      ${job.kind === "monster" && ["completed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-repair-ground-mesh="${job.id}">修复已生成的底部连片网格</button>` : ""}
      ${job.has_preview && ["completed", "failed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-rebuild-multiview="${job.id}" data-strategy="front-back">Pixal3D 正反双视角重建</button><button class="link-btn" data-rebuild-multiview="${job.id}" data-strategy="four">Pixal3D 四视角重建</button>` : ""}
      ${["completed", "failed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-preserve-high-fidelity="${job.params?.source_job || job.id}">保留高精度原网格并打包</button>` : ""}
      ${["completed", "failed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-reprocess="${job.id}">重新优化网格</button>` : ""}
      ${["failed", "completed", "review_required", "rejected"].includes(job.status) ? `<button class="link-btn" data-retry="${job.id}">重新执行</button>` : ""}</div>
    </article>`;
  }).join("") : `<div class="panel muted">当前筛选条件下没有任务。</div>`;
}

async function refreshAssets() {
  const data = await api("/api/assets");
  const signature = JSON.stringify(data.assets.map((asset) => [asset.id, asset.title, asset.status, asset.has_preview]));
  if (signature === assetsSignature) return;
  assetsSignature = signature;
  assetCache = data.assets;
  if (currentPage === "assets") renderAssets();
}

function renderAssets() {
  const search = $("#asset-search").value.trim().toLowerCase();
  const selectedType = $("#asset-type").value;
  const assets = assetCache.filter((asset) =>
    asset.title.toLowerCase().includes(search) && (selectedType === "all" || asset.kind === selectedType));
  $("#asset-total").textContent = `${assets.length} 个资产`;
  $("#asset-list").innerHTML = assets.length ? assets.map((asset) => {
    const url = `/api/jobs/${asset.id}/file/`;
    return `<article class="asset-card"><div class="asset-thumb">${asset.has_preview ? `<img loading="lazy" src="${url}input.png" alt="${escapeHtml(asset.title)}">` : `<div class="asset-thumb-empty">3D</div>`}<span class="asset-kind-tag">${escapeHtml(types[asset.kind] ?? asset.kind)}</span></div>
    <div class="asset-info"><h3>${escapeHtml(asset.title)}</h3><p>${asset.mode === "parts" ? "独立部件" : asset.mode === "import" ? "GLB 导入" : "完整三维模型"} · ${escapeHtml(asset.created_at.slice(0, 10))}${asset.status === "review_required" ? " · 等待外观审核" : asset.status === "rejected" ? " · 外观不合格" : ""}</p>
      <div class="asset-actions"><a class="link-btn asset-open" href="/?asset=${asset.id}">查看模型与质量</a><a class="link-btn" href="${url}godot_asset.zip">下载资源包</a><button class="link-btn" data-reprocess="${asset.id}">重新优化</button>${asset.has_preview ? `<button class="link-btn" data-rebuild-multiview="${asset.id}" data-strategy="four">Pixal3D 四视角重建</button>` : ""}${asset.kind === "monster" && asset.has_preview ? `<button class="link-btn" data-repair-ground="${asset.id}">清理脚底地面并重建</button><button class="link-btn" data-repair-ground-mesh="${asset.id}">修复现有模型地面网格</button>` : ""}${["character", "monster"].includes(asset.kind) ? `<button class="link-btn" data-texture-repair="${asset.id}">修复黑色贴图残留</button>` : ""}${asset.status === "review_required" ? `<button class="link-btn" data-review-action="approve" data-review-id="${asset.id}">外观合格</button><button class="link-btn" data-review-action="reject" data-review-id="${asset.id}">外观不合格</button>` : ""}</div></div></article>`;
  }).join("") : `<div class="panel muted">当前条件下没有可查看的资产。</div>`;
}

$("#asset-search").addEventListener("input", renderAssets);
$("#asset-type").addEventListener("change", renderAssets);
document.querySelectorAll("[data-job-filter]").forEach((button) => button.addEventListener("click", () => {
  jobFilter = button.dataset.jobFilter;
  document.querySelectorAll("[data-job-filter]").forEach((item) => item.classList.toggle("active", item === button));
  refreshJobs();
}));

async function refreshSystem() {
  const info = await api("/api/system");
  $("#connection-dot").classList.add("ok");
  $("#connection-text").textContent = "工作台连接正常";
  $("#gpu-badge").textContent = info.gpu.available ? info.gpu.devices.map((device) => device.name).join(" / ") : "等待 GPU";
  if (currentPage !== "system") return;
  const names = {anime: "WAI Illustrious v17", pixal3d: "Pixal3D", partcrafter: "PartCrafter", skintokens: "SkinTokens", blender: "Blender", godot: "Godot 4.7"};
  const cards = Object.entries(info.software).map(([key, value]) => {
    const installed = Boolean(value.installed);
    return `<article class="system-card"><h3>${names[key]}</h3><p class="${installed ? "status-good" : "status-bad"}">${installed ? "● 已安装" : "● 需要安装"}</p>${key === "anime" ? `<p>模型：${escapeHtml(value.model)}</p>` : ""}</article>`;
  });
  cards.push(`<article class="system-card"><h3>GPU 与资源</h3><p>${info.gpu.available ? info.gpu.devices.map((device) => `${escapeHtml(device.name)}，空闲显存 ${device.memory_free_mib} MiB`).join("<br>") : escapeHtml(info.gpu.reason || "尚未检测到 GPU")}</p><p>数据盘剩余 ${info.storage.free_gb} GB</p></article>`);
  cards.push(`<article class="system-card"><h3>CUDA 驱动</h3><p class="${info.cuda.ready ? "status-good" : "status-bad"}">${escapeHtml(info.cuda.diagnostic)}</p></article>`);
  cards.push(`<article class="system-card"><h3>模型运行资源</h3><p class="${info.gpu_headroom.ready ? "status-good" : "status-bad"}">${info.gpu_headroom.ready ? "可以开始模型推理" : `GPU ${escapeHtml(info.gpu_headroom.gpu)} 正在执行其他任务`}</p>${info.gpu_headroom.required_mib ? `<p>空闲 ${info.gpu_headroom.free_mib} MiB / 预留 ${info.gpu_headroom.required_mib} MiB</p>` : ""}</article>`);
  $("#system-cards").innerHTML = cards.join("");
}

document.addEventListener("click", async (event) => {
  const groundMeshButton = event.target.closest("[data-repair-ground-mesh]");
  if (groundMeshButton) {
    groundMeshButton.disabled = true;
    const body = new FormData();
    body.set("height_ratio", "0.035");
    try {
      const result = await api(`/api/jobs/${groundMeshButton.dataset.repairGroundMesh}/repair-ground-mesh`, {method: "POST", body});
      notify(`底部连片面积 ${(result.ground_footprint_before * 100).toFixed(1)}% → ${(result.ground_footprint_after * 100).toFixed(1)}%，游戏资源打包任务已登记`);
      navigate("jobs");
    } catch (error) {
      notify(`底部网格修复失败：${error.message}`, 11000);
      groundMeshButton.disabled = false;
    }
    return;
  }
  const groundButton = event.target.closest("[data-repair-ground]");
  if (groundButton) {
    groundButton.disabled = true;
    try {
      const result = await api(`/api/jobs/${groundButton.dataset.repairGround}/repair-ground`, {method: "POST"});
      notify(`怪物脚底地面清理与 Pixal3D 重建任务已提交：${result.job_id.slice(0, 8)}`);
      navigate("jobs");
    } catch (error) {
      notify(`怪物地面修复提交失败：${error.message}`, 11000);
      groundButton.disabled = false;
    }
    return;
  }
  const preserveButton = event.target.closest("[data-preserve-high-fidelity]");
  if (preserveButton) {
    preserveButton.disabled = true;
    const params = new FormData();
    params.set("preserve_geometry", "true");
    params.set("target_faces", "500000");
    try {
      const result = await api(`/api/jobs/${preserveButton.dataset.preserveHighFidelity}/reprocess`, {method: "POST", body: params});
      notify(`已提交高保真原始模型打包任务：${result.job_id.slice(0, 8)}`);
      navigate("jobs");
    } catch (error) {
      notify(`高保真打包提交失败：${error.message}`, 11000);
      preserveButton.disabled = false;
    }
    return;
  }
  const multiviewButton = event.target.closest("[data-rebuild-multiview]");
  if (multiviewButton) {
    multiviewButton.disabled = true;
    const params = new FormData();
    params.set("multi_view_strategy", multiviewButton.dataset.strategy);
    params.set("pixal_low_vram", "true");
    try {
      const result = await api(`/api/jobs/${multiviewButton.dataset.rebuildMultiview}/rebuild-multiview`, {method: "POST", body: params});
      notify(`Pixal3D 多视角重建任务已登记：${result.job_id.slice(0, 8)}`);
      navigate("jobs");
    } catch (error) {
      notify(`多视角重建提交失败：${error.message}`, 11000);
      multiviewButton.disabled = false;
    }
    return;
  }
  const textureButton = event.target.closest("[data-texture-repair]");
  if (textureButton) {
    textureButton.disabled = true;
    try {
      const result = await api(`/api/jobs/${textureButton.dataset.textureRepair}/repair-texture`, {method: "POST"});
      notify(`已提交贴图残留修复 ${result.job_id.slice(0, 8)}`);
      navigate("jobs");
    } catch (error) {
      notify(`贴图修复失败：${error.message}`, 11000);
      textureButton.disabled = false;
    }
    return;
  }
  const reviewButton = event.target.closest("[data-review-action]");
  if (reviewButton) {
    reviewButton.disabled = true;
    try {
      await api(`/api/jobs/${reviewButton.dataset.reviewId}/${reviewButton.dataset.reviewAction}`, {method: "POST"});
      notify(reviewButton.dataset.reviewAction === "approve" ? "资产已通过外观审核" : "资产已标记为外观不合格");
      assetsSignature = "";
      await refreshJobs();
      await refreshAssets();
    } catch (error) {
      notify(error.message);
      reviewButton.disabled = false;
    }
    return;
  }
  const assetLink = event.target.closest('a[href^="/?asset="]');
  if (assetLink) {
    event.preventDefault();
    const target = new URL(assetLink.href).searchParams.get("asset");
    if (!target || !/^[0-9a-f]{32}$/.test(target)) return;
    window.history.replaceState(null, "", `/?asset=${target}`);
    navigate("assets");
    const job = await api(`/api/jobs/${target}`);
    await openViewer(job.id, job.title, job.has_preview, job.has_fast_preview);
    return;
  }
  const logButton = event.target.closest("[data-log]");
  const retryButton = event.target.closest("[data-retry]");
  const reprocessButton = event.target.closest("[data-reprocess]");
  const previewButton = event.target.closest("[data-preview]");
  if (logButton) {
    const response = await fetch(`/api/jobs/${logButton.dataset.log}/log`);
    const content = await response.text();
    const blob = new Blob([content], {type: "text/plain;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${logButton.dataset.log}.log`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  if (retryButton) {
    try {
      const result = await api(`/api/jobs/${retryButton.dataset.retry}/retry`, {method: "POST"});
      notify(`重新执行任务 ${result.job_id.slice(0, 8)}`);
      refreshJobs();
    } catch (error) { notify(error.message); }
  }
  if (reprocessButton) {
    reprocessButton.disabled = true;
    try {
      const result = await api(`/api/jobs/${reprocessButton.dataset.reprocess}/reprocess`, {method: "POST"});
      notify(`已提交真实网格优化任务 ${result.job_id.slice(0, 8)}`);
      navigate("jobs");
    } catch (error) {
      notify(`网格优化提交失败：${error.message}`, 11000);
      reprocessButton.disabled = false;
    }
  }
  if (previewButton) {
    navigate("assets");
    const job = await api(`/api/jobs/${previewButton.dataset.preview}`);
    await openViewer(job.id, job.title, job.has_preview, job.has_fast_preview);
  }
});

function closeViewer() {
  if (viewer) {
    cancelAnimationFrame(viewer.frame);
    viewer.controls.dispose();
    viewer.debugMaterials.forEach((material) => material.dispose());
    viewer.renderer.dispose();
    viewer = null;
  }
  $("#viewer-canvas").replaceChildren();
  $("#viewer-canvas").removeAttribute("data-load-state");
  $("#viewer-reference-image").removeAttribute("src");
  $("#viewer-quality").textContent = "正在读取真实网格检查结果…";
  $("#viewer-panel").hidden = true;
}

$("#viewer-close").addEventListener("click", closeViewer);

async function openViewer(id, title, hasPreview = true, hasFastPreview = false) {
  closeViewer();
  $("#viewer-panel").hidden = false;
  $("#viewer-title").textContent = title;
  const reference = $("#viewer-reference");
  const comparison = $("#viewer-panel .viewer-comparison");
  const referenceImage = $("#viewer-reference-image");
  reference.hidden = !hasPreview;
  comparison.classList.remove("no-reference");
  if (hasPreview) {
    referenceImage.onerror = () => { reference.hidden = true; comparison.classList.add("no-reference"); };
    referenceImage.src = `/api/jobs/${id}/file/input.png`;
  } else {
    comparison.classList.add("no-reference");
  }
  $("#viewer-panel").scrollIntoView({behavior: "smooth", block: "nearest"});
  const container = $("#viewer-canvas");
  container.dataset.loadState = "loading";
  const overlay = document.createElement("div");
  overlay.className = "viewer-loading";
  overlay.innerHTML = '<div class="viewer-loading-spinner" aria-hidden="true"></div><strong>正在加载真实 3D 模型</strong><span>连接服务器并读取模型文件…</span><div class="viewer-loading-track"><div></div></div>';
  container.appendChild(overlay);
  const loadingMessage = overlay.querySelector("span");
  const loadingProgress = overlay.querySelector(".viewer-loading-track div");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe8edf5);
  scene.add(new THREE.HemisphereLight(0xf5f7ff, 0x8493af, 2.3));
  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.1);
  keyLight.position.set(4, 6, 7);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xa9c6ff, 1.8);
  fillLight.position.set(-6, 3, -4);
  scene.add(fillLight);
  const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.01, 500);
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.25;
  container.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  viewer = {renderer, controls, frame: null, camera, scene, model: null, originals: new Map(), debugMaterials: [], mode: "material", resetCamera: null};
  const active = viewer;
  api(`/api/jobs/${id}`).then((job) => {
    if (viewer !== active) return;
    const label = job.params?.source_gallery ? "Qwen 四视角主原画"
      : imageModels[job.params?.image_model] || "参考原画";
    $("#viewer-reference span").textContent = label;
    $("#viewer-reference-image").alt = label;
  }).catch((error) => console.error("原画信息读取失败", error));
  document.querySelectorAll("[data-view-mode]").forEach((button) => button.classList.toggle("active", button.dataset.viewMode === "material"));
  const modelFile = hasFastPreview ? "preview.glb" : "model.glb";
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  loader.load(`/api/jobs/${id}/file/${modelFile}`, (gltf) => {
    if (viewer !== active) return;
    scene.add(gltf.scene);
    active.model = gltf.scene;
    let meshCount = 0;
    gltf.scene.traverse((node) => {
      if (node.isMesh) {
        meshCount++;
        active.originals.set(node, node.material);
      }
    });
    if (meshCount === 0) {
      container.dataset.loadState = "failed";
      overlay.classList.add("failed");
      loadingMessage.textContent = "模型文件未包含可显示的几何网格";
      return;
    }
    container.dataset.meshCount = String(meshCount);
    const bounds = new THREE.Box3().setFromObject(gltf.scene);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3()).length();
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(size * 0.8, size * 0.65, size * 0.8));
    camera.near = Math.max(0.001, size / 1000);
    camera.far = Math.max(50, size * 20);
    camera.updateProjectionMatrix();
    controls.update();
    container.dataset.loadState = "ready";
    overlay.remove();
    active.resetCamera = () => {
      controls.target.copy(center);
      camera.position.copy(center).add(new THREE.Vector3(size * 0.8, size * 0.65, size * 0.8));
      controls.update();
    };
  }, (event) => {
    if (viewer !== active) return;
    if (event.lengthComputable && event.total > 0) {
      const percentage = Math.min(100, Math.round(event.loaded / event.total * 100));
      loadingMessage.textContent = `模型传输：${percentage}%（${(event.loaded / 1048576).toFixed(1)} MB）`;
      loadingProgress.style.width = `${percentage}%`;
    } else {
      loadingMessage.textContent = `模型已接收 ${(event.loaded / 1048576).toFixed(1)} MB，正在读取几何与材质…`;
    }
  }, (error) => {
    if (viewer !== active) return;
    container.dataset.loadState = "failed";
    overlay.classList.add("failed");
    loadingMessage.textContent = `模型加载失败：${error.message}`;
    notify(`模型加载失败：${error.message}`, 10000);
  });
  api(`/api/jobs/${id}/inspect`).then((quality) => {
    if (viewer !== active) return;
    const edges = (quality.boundary_edge_ratio * 100).toFixed(2);
    const connected = (quality.largest_component_ratio * 100).toFixed(1);
    const appearance = quality.appearance;
    const reasons = [...new Set([...(quality.game_readiness_reasons || []), ...(quality.review_reasons || []), ...(appearance?.review_reasons || [])])];
    const needsRepair = quality.game_ready === false;
    const needsVisualReview = quality.visual_review_required;
    const assessment = needsRepair ? "网格结构需要修复" : needsVisualReview ? "结构检查通过 · 外观等待审核" : "网格结构检查通过";
    const silhouette = appearance ? `<div><small>原画轮廓匹配</small><strong>${(appearance.silhouette_iou * 100).toFixed(1)}%</strong></div>` : "";
    const ground = quality.ground_artifacts ? `<div><small>脚底近水平表面占比</small><strong>${(quality.ground_artifacts.ground_footprint_area_ratio * 100).toFixed(2)}%</strong></div>` : "";
    const texture = quality.texture_repair;
    const textureResult = texture ? `<div><small>修复前下半身透明纹理采样</small><strong>${(texture.before.lower_body.transparent_texture_ratio * 100).toFixed(1)}%</strong></div><div><small>修复后下半身透明纹理采样</small><strong>${(texture.after.lower_body.transparent_texture_ratio * 100).toFixed(1)}%</strong></div>` : "";
    $("#viewer-quality").innerHTML = `<div class="quality-intro"><strong>${assessment}</strong><span>结构指标与实际造型分别验收</span></div><div class="quality-metrics"><div><small>三角面</small><strong>${quality.faces.toLocaleString()}</strong></div><div><small>最大连续部分</small><strong>${connected}%</strong></div><div><small>开放边界比例</small><strong>${edges}%</strong></div><div><small>非流形边</small><strong>${quality.non_manifold_edges.toLocaleString()}</strong></div><div><small>纹理</small><strong>${quality.images} 张</strong></div><div><small>骨骼</small><strong>${quality.joints} 个</strong></div>${silhouette}${ground}${textureResult}</div>${reasons.length ? `<div class="quality-reasons">${reasons.map((reason) => `<p>⚠ ${escapeHtml(reason)}</p>`).join("")}</div>` : ""}`;
  }).catch((error) => { if (viewer === active) $("#viewer-quality").textContent = `质量检查失败：${error.message}`; });
  function render() {
    if (!viewer || viewer.renderer !== renderer) return;
    controls.update();
    renderer.render(scene, camera);
    viewer.frame = requestAnimationFrame(render);
  }
  render();
}

document.querySelectorAll("[data-view-mode]").forEach((button) => button.addEventListener("click", () => {
  if (!viewer?.model) return;
  viewer.mode = button.dataset.viewMode;
  viewer.debugMaterials.forEach((material) => material.dispose());
  viewer.debugMaterials = [];
  viewer.originals.forEach((material, mesh) => {
    if (viewer.mode === "material") {
      mesh.material = material;
    } else {
      const debug = viewer.mode === "wire"
        ? new THREE.MeshBasicMaterial({color: 0xb7d0f4, wireframe: true, side: THREE.DoubleSide})
        : new THREE.MeshStandardMaterial({color: 0xcbd6e5, roughness: 0.86, metalness: 0.0, side: THREE.DoubleSide});
      mesh.material = debug;
      viewer.debugMaterials.push(debug);
    }
  });
  document.querySelectorAll("[data-view-mode]").forEach((item) => item.classList.toggle("active", item === button));
}));
$("#viewer-reset").addEventListener("click", () => viewer?.resetCamera?.());
window.addEventListener("resize", () => {
  if (!viewer) return;
  const container = $("#viewer-canvas");
  viewer.camera.aspect = container.clientWidth / container.clientHeight;
  viewer.camera.updateProjectionMatrix();
  viewer.renderer.setSize(container.clientWidth, container.clientHeight);
});

async function tick() {
  try {
    await refreshJobs();
    if (currentPage === "system") await refreshSystem();
    if (currentPage === "assets") await refreshAssets();
    if (currentPage === "create") {
      const status = await api("/api/system");
      $("#connection-dot").classList.add("ok");
      $("#connection-text").textContent = "工作台连接正常";
      $("#gpu-badge").textContent = status.gpu.available ? status.gpu.devices[0].name : "等待 GPU";
    }
  } catch (error) {
    $("#connection-dot").classList.remove("ok");
    $("#connection-text").textContent = "服务连接异常";
    console.error("工作台同步失败", error);
  }
}

tick();
setInterval(tick, 4000);

const requestedAsset = new URLSearchParams(window.location.search).get("asset");
if (requestedAsset && /^[0-9a-f]{32}$/.test(requestedAsset)) {
  api(`/api/jobs/${requestedAsset}`).then(async (job) => {
    if (["completed", "review_required", "rejected"].includes(job.status)) {
      navigate("assets");
      await openViewer(job.id, job.title, job.has_preview, job.has_fast_preview);
    } else {
      navigate("jobs");
      notify(`${job.title}：${job.stage}，完成后可以查看 3D 模型`, 9000);
    }
  }).catch((error) => notify(`无法打开资产：${error.message}`, 9000));
}

