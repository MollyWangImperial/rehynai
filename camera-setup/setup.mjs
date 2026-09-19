import { checkFraming, createSetupTracker, project } from "./framing.mjs";

const $ = (id) => document.getElementById(id);
const query = new URLSearchParams(location.search);
const purpose = query.get("purpose") === "exercise" ? "exercise" : "assessment";
const devices = {
  iphone: ["iPhone", "Stand your iPhone upright in a secure holder. Keep the screen facing you."],
  phone: ["smartphone", "Stand your phone upright in a secure holder. Keep the screen facing you."],
  tablet: ["iPad or tablet", "Secure your tablet upright in a stable stand. Keep the screen facing you."],
  laptop: ["laptop", "Put your laptop on a stable surface. Face the screen and keep the camera above it uncovered."],
  webcam: ["webcam", "Secure your webcam on a stable mount facing you. Keep your screen where you can see it."],
  other_camera: ["camera", "Secure a camera that works with this browser, facing you. Keep its lens uncovered."],
};
const savedDevices = (query.get("devices") || "").split(",").filter((id) => id in devices || id === "none");
let stage = "choose";
let device = "iphone";
let stream = null;
let model = null;
let session = 0;
let animation = 0;
let frameReady = false;
let lastFrameAt = 0;
let lastDetectedAt = 0;
let lastVideoTime = -1;
let activeCameraId = "";
const tracker = createSetupTracker();
let setupChecks = { steady: false, position: false, framing: false };
const video = $("video");
const canvas = $("overlay");
const ctx = canvas.getContext("2d");
const links = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [15, 19], [16, 20]];

function bridge(type) {
  const message = JSON.stringify({ type });
  if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(message);
  else if (window.parent !== window) window.parent.postMessage(message, "*");
  else if (type === "camera_setup_exit") location.assign("/");
}

function show(next) {
  stage = next;
  for (const id of ["choose", "placement", "test", "no-camera"]) $(id).hidden = id !== next;
  $("step-label").textContent = `Camera setup ${next === "test" ? 3 : next === "placement" ? 2 : 1} of 3`;
  window.scrollTo(0, 0);
  $(next).querySelector("h1")?.focus({ preventScroll: true });
}

function chooseDevice(id) {
  stopCamera();
  if (id === "none") { show("no-camera"); return; }
  device = id;
  $("placement-title").textContent = `Place your ${devices[id][0]} like this`;
  $("device-placement").textContent = devices[id][1];
  const phone = id === "iphone" || id === "phone";
  $("placement").classList.toggle("phone-placement", phone);
  $("illustration").hidden = !phone;
  $("play-demo").hidden = !phone;
  document.querySelector(".setup-layout").classList.toggle("no-illustration", !phone);
  show("placement");
}

const ordered = [...new Set([...savedDevices, ...Object.keys(devices), "none"])];
for (const id of ordered) {
  const button = document.createElement("button");
  button.textContent = id === "none" ? "No camera available" : devices[id][0].replace(/^./, (s) => s.toUpperCase());
  if (id === "iphone") button.textContent = "iPhone";
  if (id === "tablet") button.textContent = "iPad or tablet";
  button.dataset.device = id;
  button.addEventListener("click", () => chooseDevice(id));
  $("device-options").append(button);
}

function setStatus(text, busy = true) {
  $("status-text").textContent = text;
  $("camera-status").querySelector(".spinner").hidden = !busy;
}

function refreshReady() {
  const running = !!stream && stream.getVideoTracks().some((track) => track.readyState === "live") && !video.paused;
  const measured = running && frameReady && performance.now() - lastFrameAt < 1800;
  const ready = measured;
  $("continue").disabled = !ready;
  $("continue").textContent = ready ? `Continue to ${purpose}` : "Checking camera automatically...";
  const fresh = running && performance.now() - lastFrameAt < 1800;
  for (const [id, check, pending, passed] of [
    ["steady", "steady", "Checking view steadiness", "View is steady"],
    ["position", "position", "Checking head and shoulders", "Head and shoulders in view"],
    ["frame", "framing", "Checking arms and hands", "Arms and hands in view"],
  ]) {
    const ok = fresh && setupChecks[check];
    $(`${id}-icon`).className = ok ? "check" : "spinner";
    $(`${id}-icon`).textContent = ok ? "\u2713" : "";
    $(`${id}-text`).textContent = ok ? passed : pending;
  }
  if (measured) setStatus("All camera checks complete", false);
  else if (running && !fresh) {
    setStatus("Waiting for a fresh camera image...");
    $("frame-hint").textContent = "The camera image has paused. Keep Rehyn open while the preview resumes.";
  }
}

function stopCamera() {
  session += 1;
  cancelAnimationFrame(animation);
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
  model?.close();
  model = null;
  frameReady = false;
  setupChecks = { steady: false, position: false, framing: false };
  tracker.reset();
  lastFrameAt = 0;
  lastDetectedAt = 0;
  lastVideoTime = -1;
  $("live").hidden = true;
  $("preview-empty").hidden = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  refreshReady();
}

function timeout(promise, milliseconds, message) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); })]).finally(() => clearTimeout(timer));
}

function failed(error, token) {
  if (token !== session) return;
  stopCamera();
  const denied = ["NotAllowedError", "PermissionDeniedError"].includes(error.name);
  const missing = ["NotFoundError", "DevicesNotFoundError"].includes(error.name);
  const busy = ["NotReadableError", "TrackStartError"].includes(error.name);
  $("error").textContent = denied ? "Camera access was not allowed. Allow camera access for Rehyn in your browser settings, then try again."
    : missing ? "No camera was found. Connect a camera or choose a different device."
    : busy ? "The camera is busy. Close other camera apps and try again."
    : error.message || "The camera check stopped. Close other camera apps and try again.";
  $("error").hidden = false;
  $("retry").hidden = false;
  $("continue").hidden = true;
  setStatus("Camera check paused", false);
}

function draw(landmarks, geometry) {
  const width = geometry[2], height = geometry[3];
  const pixelRatio = Math.min(devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width * pixelRatio) || canvas.height !== Math.round(height * pixelRatio)) {
    canvas.width = Math.round(width * pixelRatio); canvas.height = Math.round(height * pixelRatio);
  }
  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#94efbc"; ctx.lineWidth = 3;
  // Corner guides stay within the visible viewport, including on portrait phones.
  for (const [x, y, dx, dy] of [[.07,.1,1,1],[.93,.1,-1,1],[.07,.93,1,-1],[.93,.93,-1,-1]]) {
    ctx.beginPath(); ctx.moveTo(x*width+dx*24,y*height); ctx.lineTo(x*width,y*height); ctx.lineTo(x*width,y*height+dy*24); ctx.stroke();
  }
  if (!landmarks) return;
  const point = (i) => project(landmarks[i], ...geometry);
  ctx.strokeStyle = "#76e2b6";
  for (const [a, b] of links) {
    if ((landmarks[a]?.visibility ?? 0) < .45 || (landmarks[b]?.visibility ?? 0) < .45) continue;
    const p = point(a), q = point(b);
    ctx.beginPath(); ctx.moveTo(p.x,p.y); ctx.lineTo(q.x,q.y); ctx.stroke();
  }
  for (const i of [11,12,13,14,15,16]) {
    if ((landmarks[i]?.visibility ?? 0) < .45) continue;
    const p = point(i);
    ctx.fillStyle = "#dcfff3"; ctx.beginPath(); ctx.arc(p.x,p.y,6,0,Math.PI*2); ctx.fill(); ctx.stroke();
  }
}

function frame(now, token) {
  if (token !== session || !model || !stream) return;
  try {
    if (video.readyState >= 2 && video.currentTime !== lastVideoTime && now - lastDetectedAt >= 100) {
      lastVideoTime = video.currentTime;
      lastDetectedAt = now;
      const result = model.detectForVideo(video, now);
      const landmarks = result.landmarks?.[0];
      const rect = canvas.getBoundingClientRect();
      const geometry = [video.videoWidth, video.videoHeight, rect.width, rect.height, getComputedStyle(video).objectFit];
      const framing = checkFraming(landmarks, geometry);
      const setup = tracker.update(framing, landmarks, geometry, now);
      frameReady = setup.ready;
      setupChecks = setup.checks;
      lastFrameAt = now;
      $("frame-hint").textContent = setup.hint;
      if (!frameReady) setStatus("Checking your camera...");
      draw(landmarks, geometry);
    }
    refreshReady();
    animation = requestAnimationFrame((time) => frame(time, token));
  } catch (error) { failed(error, token); }
}

async function startCamera() {
  stopCamera();
  show("test");
  const token = session;
  $("error").hidden = true;
  $("retry").hidden = true;
  $("continue").hidden = false;
  setStatus("Opening camera...");
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access needs a secure browser connection. Open Rehyn using HTTPS.");
    const cameraRequest = navigator.mediaDevices.getUserMedia({ audio: false, video: { ...(activeCameraId ? { deviceId: { exact: activeCameraId } } : { facingMode: "user" }), width: { ideal: 720 }, height: { ideal: 960 } } }).then((camera) => {
      if (session !== token) camera.getTracks().forEach((track) => track.stop());
      return camera;
    });
    const camera = await timeout(cameraRequest, 45000, "Camera permission is still waiting. Allow camera access, then try again.");
    if (token !== session) return;
    stream = camera;
    video.srcObject = camera;
    await timeout(video.play(), 15000, "The camera preview could not start. Close other camera apps and try again.");
    if (token !== session) return;
    $("preview-empty").hidden = true;
    $("live").hidden = false;
    const inputs = await navigator.mediaDevices.enumerateDevices().catch(() => []);
    if (token !== session) return;
    const cameras = inputs.filter((input) => input.kind === "videoinput");
    $("camera-source").replaceChildren();
    cameras.forEach((input, index) => {
      const option = new Option(input.label || `Camera ${index + 1}`, input.deviceId);
      $("camera-source").append(option);
    });
    $("camera-source-label").hidden = cameras.length < 2;
    const currentId = camera.getVideoTracks()[0]?.getSettings().deviceId;
    if (currentId) $("camera-source").value = currentId;
    for (const track of camera.getTracks()) track.addEventListener("ended", () => failed(new Error("The camera disconnected. Reconnect it and try again."), token));
    setStatus("Loading camera check...");
    const vision = await timeout(import("/vendor/mediapipe/vision_bundle.mjs"), 30000, "The camera model could not load. Check your connection and try again.");
    if (token !== session) return;
    const modelRequest = (async () => {
      const files = await vision.FilesetResolver.forVisionTasks("/vendor/mediapipe/wasm");
      if (token !== session) return null;
      const loaded = await vision.PoseLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: "/vendor/mediapipe/models/pose_landmarker_lite.task" },
        runningMode: "VIDEO", numPoses: 1, minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5, minTrackingConfidence: .5,
      });
      if (token !== session) { loaded.close(); return null; }
      return loaded;
    })();
    const loaded = await timeout(modelRequest, 45000, "The camera check took too long to load. Check your connection and try again.");
    if (token !== session || !loaded) return;
    model = loaded;
    animation = requestAnimationFrame((time) => frame(time, token));
  } catch (error) { failed(error, token); }
}

$("open-check").addEventListener("click", startCamera);
$("retry").addEventListener("click", startCamera);
$("camera-source").addEventListener("change", () => { activeCameraId = $("camera-source").value; startCamera(); });
$("stop").addEventListener("click", () => { stopCamera(); show("placement"); });
$("continue").addEventListener("click", () => {
  refreshReady();
  if ($("continue").disabled) return;
  stopCamera();
  bridge("camera_setup_ready");
});
$("back").addEventListener("click", () => {
  stopCamera();
  if (stage === "test") show("placement");
  else if (stage !== "choose") show("choose");
  else bridge("camera_setup_exit");
});
$("change-device").addEventListener("click", () => show("choose"));
$("choose-again").addEventListener("click", () => show("choose"));
$("no-camera-back").addEventListener("click", () => bridge("camera_setup_exit"));
window.addEventListener("pagehide", stopCamera);
document.addEventListener("visibilitychange", () => {
  if (document.hidden && stage === "test") { stopCamera(); show("placement"); }
});

const captions = [
  "1. Stand your phone upright in a secure holder, with the screen facing you.",
  "2. Set the camera at your shoulder height. For seated tasks, match your seated shoulder height.",
  "3. Move the camera until your head, shoulders, arms and hands fit. Sit safely for arm and hand tasks.",
];
let demoStep = 0, demoTimer = 0;
function updateDemo() {
  document.querySelector(".demo-image").dataset.step = String(demoStep);
  $("demo-caption").textContent = captions[demoStep];
  $("demo-count").textContent = `${demoStep + 1} / 3`;
}
function pauseDemo() { clearInterval(demoTimer); demoTimer = 0; $("demo-toggle").textContent = "Play"; }
function playDemo() {
  if (demoStep === 2) { demoStep = 0; updateDemo(); }
  pauseDemo(); $("demo-toggle").textContent = "Pause";
  demoTimer = setInterval(() => { if (demoStep === 2) pauseDemo(); else { demoStep++; updateDemo(); } }, 5000);
}
$("play-demo").addEventListener("click", () => { demoStep = 0; updateDemo(); $("demo").showModal(); playDemo(); });
$("close-demo").addEventListener("click", () => $("demo").close());
$("demo").addEventListener("close", pauseDemo);
$("demo-toggle").addEventListener("click", () => demoTimer ? pauseDemo() : playDemo());
$("demo-next").addEventListener("click", () => { demoStep = (demoStep + 1) % 3; updateDemo(); });
window.addEventListener("pagehide", pauseDemo);

if (savedDevices.length === 1) chooseDevice(savedDevices[0]);
else if (/iPhone/i.test(navigator.userAgent) && !savedDevices.includes("none")) chooseDevice("iphone");
else show("choose");
