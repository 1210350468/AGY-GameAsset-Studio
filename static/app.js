import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (selector) => document.querySelector(selector);
const pages = {create: "制作游戏资产", jobs: "任务进度", assets: "资产库", system: "模型与设备"};
const types = {character: "角色", monster: "怪物", weapon: "武器", equipment: "装备", prop: "道具", scene: "场景"};
let currentPage = "create";
let viewer = null;
let notificationTimer = null;
let assetCache = [];
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
});
$("#clear-image").addEventListener("click", () => {
  $("#asset-image").value = "";
  $("#image-preview").removeAttribute("src");
  $("#image-preview-wrap").hidden = true;
  $("#upload-text").textContent = "选择角色原画、装备图片或怪物设定图";
});

$("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
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
  const failedCount = data.jobs.filter((job) => job.status === "failed").length;
  $("#job-count").textContent = activeCount;
  if (currentPage !== "jobs") return;
  $("#job-summary").innerHTML = `<div><small>队列与进行中</small><strong>${activeCount}</strong></div><div><small>已完成的资产</small><strong>${completedCount}</strong></div><div><small>异常任务</small><strong>${failedCount}</strong></div>`;
  const filtered = data.jobs.filter((job) => jobFilter === "all" || (jobFilter === "active" ? ["queued", "running"].includes(job.status) : job.status === jobFilter));
  $("#job-list").innerHTML = filtered.length ? filtered.map((job) => {
    const status = {queued: "等待处理", running: "正在制作", completed: "已完成", failed: "失败"}[job.status] ?? job.status;
    const fileUrl = `/api/jobs/${job.id}/file/`;
    return `<article class="job-card">
      <div class="job-head"><strong>${escapeHtml(job.title)}</strong><span class="label-state ${escapeHtml(job.status)}">${status}</span></div>
      <div class="job-meta">${escapeHtml(types[job.kind] || job.kind)} · ${job.mode === "whole" ? "完整模型" : job.mode === "parts" ? "拆分部件" : "GLB 优化"} · ${escapeHtml(job.stage)} · ${escapeHtml(job.created_at.slice(0, 19).replace("T", " "))}</div>
      ${job.mode !== "import" && !["queued", "生成二次元原画"].includes(job.stage) ? `<a class="job-concept-link" href="${fileUrl}input.png" target="_blank" rel="noopener noreferrer"><img src="${fileUrl}input.png" alt="${escapeHtml(job.title)} 原画" loading="lazy" onerror="this.parentElement.hidden=true"></a>` : ""}
      <div class="progress-track"><div style="width:${Math.round(job.progress * 100)}%"></div></div>
      ${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ""}
      <div class="job-actions"><button class="link-btn" data-log="${job.id}">查看日志</button>
      ${job.status === "completed" ? `<a class="link-btn" href="${fileUrl}model.glb">下载 GLB</a><a class="link-btn" href="${fileUrl}godot_asset.zip">下载 Godot 资源包</a><a class="link-btn" href="/?asset=${job.id}">3D 预览</a>` : ""}
      ${["completed", "failed"].includes(job.status) ? `<button class="link-btn" data-reprocess="${job.id}">重新优化网格</button>` : ""}
      ${["failed", "completed"].includes(job.status) ? `<button class="link-btn" data-retry="${job.id}">重新执行</button>` : ""}</div>
    </article>`;
  }).join("") : `<div class="panel muted">当前筛选条件下没有任务。</div>`;
}

async function refreshAssets() {
  const data = await api("/api/assets");
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
    return `<article class="asset-card"><div class="asset-thumb"><img loading="lazy" src="${url}input.png" alt="${escapeHtml(asset.title)}" onerror="this.hidden=true"><span class="asset-kind-tag">${escapeHtml(types[asset.kind] ?? asset.kind)}</span></div>
    <div class="asset-info"><h3>${escapeHtml(asset.title)}</h3><p>${asset.mode === "parts" ? "独立部件" : asset.mode === "import" ? "GLB 导入" : "完整三维模型"} · ${escapeHtml(asset.created_at.slice(0, 10))}</p>
      <div class="asset-actions"><a class="link-btn asset-open" href="/?asset=${asset.id}">查看模型与质量</a><a class="link-btn" href="${url}godot_asset.zip">下载资源包</a><button class="link-btn" data-reprocess="${asset.id}">重新优化</button></div></div></article>`;
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
    await openViewer(previewButton.dataset.preview, previewButton.dataset.title);
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
  $("#viewer-reference-image").removeAttribute("src");
  $("#viewer-quality").textContent = "正在读取真实网格检查结果…";
  $("#viewer-panel").hidden = true;
}

$("#viewer-close").addEventListener("click", closeViewer);

async function openViewer(id, title) {
  closeViewer();
  $("#viewer-panel").hidden = false;
  $("#viewer-title").textContent = title;
  const reference = $("#viewer-reference");
  const comparison = $("#viewer-panel .viewer-comparison");
  const referenceImage = $("#viewer-reference-image");
  reference.hidden = false;
  comparison.classList.remove("no-reference");
  referenceImage.onerror = () => { reference.hidden = true; comparison.classList.add("no-reference"); };
  referenceImage.src = `/api/jobs/${id}/file/input.png`;
  $("#viewer-panel").scrollIntoView({behavior: "smooth", block: "nearest"});
  const container = $("#viewer-canvas");
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
  document.querySelectorAll("[data-view-mode]").forEach((button) => button.classList.toggle("active", button.dataset.viewMode === "material"));
  new GLTFLoader().load(`/api/jobs/${id}/file/model.glb`, (gltf) => {
    if (viewer !== active) return;
    scene.add(gltf.scene);
    active.model = gltf.scene;
    gltf.scene.traverse((node) => { if (node.isMesh) active.originals.set(node, node.material); });
    const bounds = new THREE.Box3().setFromObject(gltf.scene);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3()).length();
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(size * 0.8, size * 0.65, size * 0.8));
    camera.near = Math.max(0.001, size / 1000);
    camera.far = Math.max(50, size * 20);
    camera.updateProjectionMatrix();
    controls.update();
    active.resetCamera = () => {
      controls.target.copy(center);
      camera.position.copy(center).add(new THREE.Vector3(size * 0.8, size * 0.65, size * 0.8));
      controls.update();
    };
  }, undefined, (error) => notify(`无法加载模型：${error.message}`, 9000));
  api(`/api/jobs/${id}/inspect`).then((quality) => {
    if (viewer !== active) return;
    const edges = (quality.boundary_edge_ratio * 100).toFixed(2);
    const connected = (quality.largest_component_ratio * 100).toFixed(1);
    $("#viewer-quality").innerHTML = `<div class="quality-intro"><strong>${quality.review_required ? "结构需要检查" : "结构检查通过"}</strong><span>依据实际 GLB 网格统计</span></div><div class="quality-metrics"><div><small>三角面</small><strong>${quality.faces.toLocaleString()}</strong></div><div><small>最大连续部分</small><strong>${connected}%</strong></div><div><small>开放边界比例</small><strong>${edges}%</strong></div><div><small>非流形边</small><strong>${quality.non_manifold_edges.toLocaleString()}</strong></div><div><small>纹理</small><strong>${quality.images} 张</strong></div><div><small>骨骼</small><strong>${quality.joints} 个</strong></div></div>${quality.review_reasons.length ? `<div class="quality-reasons">${quality.review_reasons.map((reason) => `<p>⚠ ${escapeHtml(reason)}</p>`).join("")}</div>` : ""}`;
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
    if (job.status === "completed") {
      navigate("assets");
      await openViewer(job.id, job.title);
    } else {
      navigate("jobs");
      notify(`${job.title}：${job.stage}，完成后可以查看 3D 模型`, 9000);
    }
  }).catch((error) => notify(`无法打开资产：${error.message}`, 9000));
}

