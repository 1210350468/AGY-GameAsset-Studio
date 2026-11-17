import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (selector) => document.querySelector(selector);
const pages = {create: "制作游戏资产", jobs: "任务进度", assets: "资产库", system: "模型与设备"};
const types = {character: "角色", monster: "怪物", weapon: "武器", equipment: "装备", prop: "道具", scene: "场景"};
let currentPage = "create";
let viewer = null;
let notificationTimer = null;

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
  $("#job-count").textContent = data.jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  if (currentPage !== "jobs") return;
  $("#job-list").innerHTML = data.jobs.length ? data.jobs.map((job) => {
    const status = {queued: "等待处理", running: "正在制作", completed: "已完成", failed: "失败"}[job.status] ?? job.status;
    const fileUrl = `/api/jobs/${job.id}/file/`;
    return `<article class="job-card">
      <div class="job-head"><strong>${escapeHtml(job.title)}</strong><span class="label-state ${escapeHtml(job.status)}">${status}</span></div>
      <div class="job-meta">${escapeHtml(types[job.kind] || job.kind)} · ${job.mode === "whole" ? "完整模型" : job.mode === "parts" ? "拆分部件" : "GLB 优化"} · ${escapeHtml(job.stage)} · ${escapeHtml(job.created_at.slice(0, 19).replace("T", " "))}</div>
      <div class="progress-track"><div style="width:${Math.round(job.progress * 100)}%"></div></div>
      ${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ""}
      <div class="job-actions"><button class="link-btn" data-log="${job.id}">查看日志</button>
      ${job.status === "completed" ? `<a class="link-btn" href="${fileUrl}model.glb">下载 GLB</a><a class="link-btn" href="${fileUrl}godot_asset.zip">下载 Godot 资源包</a><button class="link-btn" data-preview="${job.id}" data-title="${escapeHtml(job.title)}">3D 预览</button>` : ""}
      ${["failed", "completed"].includes(job.status) ? `<button class="link-btn" data-retry="${job.id}">重新执行</button>` : ""}</div>
    </article>`;
  }).join("") : `<div class="panel muted">目前还没有资产任务，可以从「资产制作」开始。</div>`;
}

async function refreshAssets() {
  const data = await api("/api/assets");
  if (currentPage !== "assets") return;
  $("#asset-list").innerHTML = data.assets.length ? data.assets.map((asset) => {
    const url = `/api/jobs/${asset.id}/file/`;
    return `<article class="asset-card"><div class="asset-thumb"><img loading="lazy" src="${url}input.png" alt="${escapeHtml(asset.title)}" onerror="this.hidden=true"></div>
    <div class="asset-info"><h3>${escapeHtml(asset.title)}</h3><p>${escapeHtml(types[asset.kind] ?? asset.kind)} · ${escapeHtml(asset.created_at.slice(0, 10))}</p>
      <div class="asset-actions"><button class="link-btn" data-preview="${asset.id}" data-title="${escapeHtml(asset.title)}">预览模型</button><a class="link-btn" href="${url}godot_asset.zip">下载资源包</a></div></div></article>`;
  }).join("") : `<div class="panel muted">已完成的资产会自动出现在这里。</div>`;
}

async function refreshSystem() {
  const info = await api("/api/system");
  $("#connection-dot").classList.add("ok");
  $("#connection-text").textContent = "工作台连接正常";
  $("#gpu-badge").textContent = info.gpu.available ? info.gpu.devices.map((device) => device.name).join(" / ") : "等待 GPU";
  if (currentPage !== "system") return;
  const names = {anime: "WAI Illustrious v17", pixal3d: "Pixal3D", partcrafter: "PartCrafter", skintokens: "SkinTokens", blender: "Blender"};
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
  if (previewButton) {
    navigate("assets");
    await openViewer(previewButton.dataset.preview, previewButton.dataset.title);
  }
});

function closeViewer() {
  if (viewer) {
    cancelAnimationFrame(viewer.frame);
    viewer.controls.dispose();
    viewer.renderer.dispose();
    viewer = null;
  }
  $("#viewer-canvas").replaceChildren();
  $("#viewer-panel").hidden = true;
}

$("#viewer-close").addEventListener("click", closeViewer);

async function openViewer(id, title) {
  closeViewer();
  $("#viewer-panel").hidden = false;
  $("#viewer-title").textContent = title;
  $("#viewer-panel").scrollIntoView({behavior: "smooth", block: "nearest"});
  const container = $("#viewer-canvas");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeff3fa);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x98a6c0, 2.4));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.1);
  keyLight.position.set(4, 8, 6);
  scene.add(keyLight);
  const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.01, 500);
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  viewer = {renderer, controls, frame: null};
  new GLTFLoader().load(`/api/jobs/${id}/file/model.glb`, (gltf) => {
    scene.add(gltf.scene);
    const bounds = new THREE.Box3().setFromObject(gltf.scene);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3()).length();
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(size * 0.8, size * 0.65, size * 0.8));
    camera.near = Math.max(0.001, size / 1000);
    camera.far = Math.max(50, size * 20);
    camera.updateProjectionMatrix();
    controls.update();
  }, undefined, (error) => notify(`无法加载模型：${error.message}`, 9000));
  function render() {
    if (!viewer || viewer.renderer !== renderer) return;
    controls.update();
    renderer.render(scene, camera);
    viewer.frame = requestAnimationFrame(render);
  }
  render();
}

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

