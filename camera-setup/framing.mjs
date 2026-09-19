// Use the same object-fit transform for landmark checks and the visible overlay.
export function project(point, sourceWidth, sourceHeight, width, height, fit = "contain") {
  const scale = (fit === "cover" ? Math.max : Math.min)(width / sourceWidth, height / sourceHeight);
  return {
    x: (width - sourceWidth * scale) / 2 + (1 - point.x) * sourceWidth * scale,
    y: (height - sourceHeight * scale) / 2 + point.y * sourceHeight * scale,
  };
}

export function checkFraming(landmarks, geometry) {
  const checks = { position: false, framing: false };
  const result = (hint) => ({ ready: checks.position && checks.framing, checks, hint });
  if (!landmarks?.length) return result("Face the camera so it can find your upper body.");
  const visible = (index) => {
    const point = landmarks[index];
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y) || (point.visibility ?? 0) < 0.45) return false;
    // Inferred joints outside the actual camera image must not pass simply
    // because contain-fit letterboxing projects them inside the preview box.
    if (point.x <= .02 || point.x >= .98 || point.y <= .02 || point.y >= .98) return false;
    const mapped = project(point, ...geometry);
    return mapped.x > geometry[2] * 0.04 && mapped.x < geometry[2] * 0.96 && mapped.y > geometry[3] * 0.04 && mapped.y < geometry[3] * 0.96;
  };
  const head = [0, 2, 5].every(visible);
  const shoulders = [11, 12].every(visible);
  const size = shoulders && Math.abs(landmarks[11].x - landmarks[12].x) >= .1;
  const arms = [13, 14, 15, 16].every(visible);
  const hands = [17, 19].some(visible) && [18, 20].some(visible);
  checks.position = head && shoulders && size;
  checks.framing = arms && hands;
  if (!head) return result("Bring your whole head into view, with some space above it.");
  if (!shoulders) return result("Face the camera and keep both shoulders in view.");
  if (!arms) return result("Move the camera farther away until both arms and hands fit. Ask for help if needed.");
  if (!hands) return result("Keep both hands visible, relaxed beside you or on your lap.");
  if (!size) return result("Move the camera a little closer while keeping both hands in view.");
  return result("Your upper body is in view. Let the camera and your seated position settle for a moment.");
}

// Measures steadiness of the visible upper-body view, not physical mounting or
// camera height. Small pose-estimation jitter and normal breathing are tolerated.
export function createSetupTracker() {
  const position = createFramingTracker();
  const framing = createFramingTracker();
  let samples = [], previous = null, projection = "", checkedAt = null;
  const empty = () => ({ steady: false, position: false, framing: false });
  let checks = empty();
  function reset() {
    position.reset(); framing.reset(); samples = []; previous = null;
    projection = ""; checkedAt = null; checks = empty();
  }
  return {
    reset,
    update(result, landmarks, geometry, now) {
      const key = geometry.join(":");
      if (key !== projection || (previous !== null && (now - previous > 500 || now <= previous))) reset();
      projection = key; previous = now;
      checks.position = position.update(result.checks.position, now);
      checks.framing = framing.update(result.checks.framing, now);
      if (!result.checks.position) samples = [];
      else {
        const left = landmarks[11], right = landmarks[12], nose = landmarks[0];
        const width = Math.hypot(left.x - right.x, (left.y - right.y) * geometry[1] / geometry[0]);
        samples.push({ now, x: (left.x + right.x) / 2, y: (left.y + right.y) / 2,
          noseX: nose.x, noseY: nose.y, width });
        samples = samples.filter(sample => now - sample.now <= 1600);
      }
      checks.steady = false;
      if (samples.length >= 10 && now - samples[0].now >= 1200) {
        const median = key => [...samples].sort((a,b) => a[key]-b[key])[Math.floor(samples.length/2)][key];
        const scale = Math.max(.1, median("width"));
        const center = { x: median("x"), y: median("y"), noseX: median("noseX"), noseY: median("noseY"), width: scale };
        const settled = sample => Math.hypot(sample.x-center.x, (sample.y-center.y)*geometry[1]/geometry[0])/scale < .08
          && Math.hypot(sample.noseX-center.noseX, (sample.noseY-center.noseY)*geometry[1]/geometry[0])/scale < .12
          && Math.abs(sample.width/scale-1) < .12;
        checks.steady = samples.filter(settled).length / samples.length >= .8 && settled(samples.at(-1));
      }
      if (Object.values(checks).every(Boolean)) checkedAt = now;
      // A short grace period allows approaching the phone to tap Continue.
      // It expires instead of silently approving a different camera view forever.
      const ready = checkedAt !== null && now - checkedAt <= 10000;
      return { ready, checks: ready ? { steady: true, position: true, framing: true } : { ...checks },
        hint: ready ? "All checks complete. Tap Continue, then return to your seated position."
          : !result.ready ? result.hint : "Let the camera and your seated position settle for a moment." };
    },
  };
}

export function createFramingTracker() {
  let started = null;
  let previous = null;
  return {
    update(valid, now) {
      if (previous !== null && now - previous > 500) started = null;
      previous = now;
      if (!valid) started = null;
      else if (started === null) started = now;
      return started !== null && now - started >= 1200;
    },
    reset() { started = null; previous = null; },
  };
}
