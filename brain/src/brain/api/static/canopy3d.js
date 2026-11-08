/* The canopy in three dimensions: a model of the city under a glass brain, filmed by a camera that follows the Brain's work. The
   instruments of the brain's regions are drawn by the page beside it (the rack); this module draws the city, what the Twin moved,
   the Gate that lowers each action on a string, and a director that cuts to whatever just happened, one caption at a time.

   The city is a matte massing model and what happens in it is projected on it as light: a small plan of the marks is rendered each
   frame (`plan`), and the model and its plate sample that plan, so a mark falls on roofs and walls and spills on the plate.

   Everything is drawn from the same reduced state as the Strip Board (`update(state, from)`); nothing is invented. three.js is a
   pinned copy served by the Brain itself (/vendor), so nothing is fetched on stage. If WebGL is not available this module sets
   nothing and the page keeps its flat canopy. The page's own globals (zoneName, describe, INCIDENT, FIELD, CHECK, UNIT ...) are
   read as plain names: classic scripts share them with modules.

   Two quality tiers. `high` is for a machine with a real GPU (the team's RTX): full pixel ratio, traffic on the roads, a skyline, a
   denser model, and a glow pass with a filmic grade. `light` is for a weak or software renderer and has no pass at all. The tier
   follows the GPU's own name, `?quality=` overrides it, and a run of slow frames drops `high` to `light` by itself. */

import * as THREE from "three";
import { buildBrainShell } from "/brainshell.js";

const host = document.getElementById("canopy");
const COLOR = { ground: 0x070b11, steel: 0x6d8cab, steelDim: 0x2b3d52, bone: 0xf3ecda, ember: 0xf2b552, red: 0xff5a42, window: 0xffcf8a, good: 0x4cc38a };
const col = hex => new THREE.Color(hex);
const STEEL = col(COLOR.steel), BONE = col(COLOR.bone), EMBER = col(COLOR.ember), WINDOW = col(COLOR.window);  /* made once: the frame allocates nothing */

let renderer, camera, scene, W = 0, H = 0, ok = false, quality = "light", gpuName = "";
const clock = { t: 0, last: 0 };
const uScale = { value: 800 }, uTime = { value: 0 }, uHouse = { value: 1 };
let state = null, calm = 0, calmTarget = 0, running = false;

/* ---------------------------------------------------------------- helpers */
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const hash = text => { let h = 2166136261; for (const c of String(text)) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const lerp = (a, b, k) => a + (b - a) * k;
const clamp = (x, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x));
const easeOut = k => 1 - Math.pow(1 - clamp(k), 3);
const rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;

/* Where each region sits inside the glass brain, front of the brain at +x: the senses at the back, the forward models in the
   cerebellum, triage deep in the middle, the workspace, packs and team at the front, memory low in the temporal lobe. The Gate
   sits on the brain stem, the only way out; the Twin is a partner and stays outside, beside the city. */
const POS = {
  senses: [-9.4, 10.6, 1.0], forward: [-6.4, 7.0, 0.4], triage: [-3.6, 11.6, 0.2], workspace: [3.0, 13.0, 0.2], packs: [8.0, 12.0, 0.8],
  memory: [2.4, 7.2, 1.6], sleep: [-2.6, 8.0, -0.6], reflex: [0.4, 9.8, 0.2], team: [7.2, 8.8, 0.4], gate: [0.6, 4.4, 1.0], twin: [17.2, 6.6, -1.5],
};
/* Label placement beside each region: [dx rem, dy rem, which side of the point the text block hangs from]. */
const LAB = {
  senses: [-1.7, -.9, "r"], forward: [-1.9, .1, "r"], triage: [0, -3.4, "c"], workspace: [0, -3.5, "c"], packs: [1.5, -2.1, "l"],
  memory: [1.5, -.2, "l"], sleep: [-1.5, -.9, "r"], reflex: [1.4, -.5, "l"], team: [1.7, -.9, "l"], gate: [10.8, -2.3, "l"], twin: [0, -3.5, "c"],
};
const gatePos = new THREE.Vector3(...POS.gate);

function softTexture(ring) {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  if (ring) { grad.addColorStop(0, "rgba(255,255,255,0)"); grad.addColorStop(.78, "rgba(255,255,255,0)"); grad.addColorStop(.9, "rgba(255,255,255,1)"); grad.addColorStop(.97, "rgba(255,255,255,.25)"); grad.addColorStop(1, "rgba(255,255,255,0)"); }
  else { grad.addColorStop(0, "rgba(255,255,255,1)"); grad.addColorStop(.25, "rgba(255,255,255,.45)"); grad.addColorStop(1, "rgba(255,255,255,0)"); }
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

/* Soft round points that keep their size on screen as the camera moves. Used for signals, dust, windows and traffic. */
function glowMaterial(twinkle) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    uniforms: { uScale, uTime, uTwinkle: { value: twinkle } },
    vertexShader: `attribute float aSize; attribute float aAlpha; attribute float aPhase; attribute vec3 aColor;
      uniform float uScale; uniform float uTime; uniform float uTwinkle; varying float vA; varying vec3 vC;
      void main() { vC = aColor; vA = aAlpha * (1.0 - uTwinkle + uTwinkle * (0.5 + 0.5 * sin(uTime * (0.5 + aPhase) + aPhase * 60.0)));
        vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = max(1.0, aSize * uScale / -mv.z); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `varying float vA; varying vec3 vC;
      void main() { float d = length(gl_PointCoord - 0.5) * 2.0; float a = clamp(1.0 - d, 0.0, 1.0); a *= a; gl_FragColor = vec4(vC, vA * a); gl_FragColor = linearToOutputTexel(gl_FragColor); }`,
  });
}
function pointsGeometry(n) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(n), 1));
  g.setAttribute("aAlpha", new THREE.BufferAttribute(new Float32Array(n), 1));
  g.setAttribute("aPhase", new THREE.BufferAttribute(new Float32Array(n), 1));
  g.setAttribute("aColor", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  return g;
}
function setPoint(g, i, p, size, alpha, color, phase = 0) {
  g.attributes.position.setXYZ(i, p.x, p.y, p.z); g.attributes.aSize.setX(i, size); g.attributes.aAlpha.setX(i, alpha);
  g.attributes.aPhase.setX(i, phase); g.attributes.aColor.setXYZ(i, color.r, color.g, color.b);
}

/* A region's body: a cut stone whose facets catch one light, brighter the more the region is doing, with its edges drawn crisp. */
function gem(geometry, color) {
  const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uLevel: { value: 0 }, uColor: { value: col(color) } },
    vertexShader: `varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `varying vec3 vW; uniform float uLevel; uniform vec3 uColor;
      void main() { vec3 n = normalize(cross(dFdx(vW), dFdy(vW))), v = normalize(cameraPosition - vW); if (dot(n, v) < 0.0) n = -n;
        float facet = 0.5 + 0.5 * dot(n, normalize(vec3(-0.4, 0.8, 0.45))), edge = pow(1.0 - dot(n, v), 1.6);
        gl_FragColor = vec4(uColor * (0.12 + 0.6 * facet + 0.5 * edge) * (0.24 + 1.5 * uLevel), 1.0); gl_FragColor = linearToOutputTexel(gl_FragColor); }`,
  }));
  const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color, transparent: true, opacity: .75 }));
  mesh.add(lines); mesh.userData.lines = lines; return mesh;
}

/* The path-flow material: a solid line, or a line of dots that drift along it (the team's slow path). */
function edgeMaterial(color, dash, alpha) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: col(color) }, uDash: { value: dash }, uTime, uEnergy: { value: 0 }, uAlpha: { value: alpha } },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec2 vUv; uniform vec3 uColor; uniform float uDash; uniform float uTime; uniform float uEnergy; uniform float uAlpha;
      void main() { float a = uAlpha;
        if (uDash > 0.0) { float f = fract(vUv.x * uDash - uTime * 0.28); a *= smoothstep(0.0, 0.1, f) * (1.0 - smoothstep(0.3, 0.42, f)); }
        a *= 0.45 + 0.55 * uEnergy; gl_FragColor = vec4(uColor * (0.7 + 0.9 * uEnergy), a); gl_FragColor = linearToOutputTexel(gl_FragColor); }`,
  });
}

/* ---------------------------------------------------------------- scene */
const groups = {};
const edges = new Map(), nodes = new Map();
const rings = [], signals = [];
let signalPoints, dustPoints, ringTexture, glowTexture, trafficPoints = null;
const labelLayer = document.createElement("div");
const stage = document.createElement("div");
const capEl = document.createElement("div"), hudEl = document.createElement("div");
const trailLen = 10, MAXSIG = 72, MAXDUST = 220;

function detectQuality() {
  const asked = new URLSearchParams(location.search).get("quality");
  try {
    const gl = renderer.getContext(), info = gl.getExtension("WEBGL_debug_renderer_info");
    gpuName = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || "") : "";
  } catch { gpuName = ""; }
  if (asked === "high" || asked === "light") return asked;
  return /nvidia|geforce|rtx|gtx|radeon rx|radeon pro|apple m\d/i.test(gpuName) && !/swiftshader|llvmpipe|software/i.test(gpuName) ? "high" : "light";
}

function build() {
  stage.className = "stage3d"; stage.setAttribute("aria-hidden", "true");
  const canvas = document.createElement("canvas"); stage.append(canvas);
  labelLayer.className = "labels3d"; stage.append(labelLayer);
  capEl.className = "shotcap"; capEl.setAttribute("aria-hidden", "true"); capEl.innerHTML = `<span class="tm"></span><b></b><i></i>`;
  hudEl.className = "shothud";
  labelLayer.append(capEl, hudEl);
  host.prepend(stage);
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  quality = detectQuality();
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, quality === "high" ? 2 : 1.5));
  renderer.setClearColor(0x000000, 1);
  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x070b11, 40, 95);
  /* The background is a dome, so the ground colour is drawn like everything else and needs no clear colour. */
  const sky = new THREE.Mesh(new THREE.SphereGeometry(110, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,
    vertexShader: `varying vec3 vDir; void main() { vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 vDir; void main() { float d = smoothstep(0.08, 0.8, -vDir.y); vec3 c = mix(vec3(0.0010, 0.0017, 0.0032), vec3(0.0042, 0.0070, 0.0115), d); c += vec3(0.0060, 0.0036, 0.0012) * pow(d, 3.0); c += vec3(0.0035, 0.0065, 0.012) * pow(1.0 - abs(vDir.y + 0.06), 10.0); gl_FragColor = vec4(c, 1.0); gl_FragColor = linearToOutputTexel(gl_FragColor); }`,
  }));
  sky.renderOrder = -10; sky.frustumCulled = false; scene.add(sky);
  camera = new THREE.PerspectiveCamera(36, 2, .1, 220);
  ringTexture = softTexture(true); glowTexture = softTexture(false);
  for (const name of ["brain", "city", "live", "air"]) { groups[name] = new THREE.Group(); scene.add(groups[name]); }

  buildPlan(); buildBrain(); buildAir(); buildSignals();
  post.can = renderer.capabilities.isWebGL2 && (renderer.extensions.has("EXT_color_buffer_float") || renderer.extensions.has("EXT_color_buffer_half_float"));
  buildPost();
  new ResizeObserver(resize).observe(stage); resize();
}

function resize() {
  const r = stage.getBoundingClientRect();
  if (!r.width || !r.height) return;
  W = Math.round(r.width); H = Math.round(r.height);
  renderer.setSize(W, H, false);
  camera.aspect = W / H; camera.updateProjectionMatrix();
  uScale.value = H * renderer.getPixelRatio() / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
  sizePost();
  if (!running) draw(0);
}

function glowSprite(color, size) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture, color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
  s.scale.set(size, size, 1); return s;
}
function wire(geometry, color, opacity = .8) { return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity })); }
function solid(geometry, color) { return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true })); }

/* The brain: one small body per region, drawn as a distinct shape so a region can be told apart without its colour. */
const gate = { group: null };
const shell = { glass: null, index: new Map() };
function buildBrain() {
  shell.glass = buildBrainShell(THREE, quality, { pointsGeometry, setPoint, glowMaterial, col });
  groups.brain.add(shell.glass.group);
  NODES.forEach((n, i) => { shell.index.set(n.id, i); shell.glass.tint[i].set(...col(n.id === "team" || n.id === "gate" ? COLOR.ember : COLOR.bone).toArray()); });
  for (const n of NODES) {
    const g = new THREE.Group(); g.position.set(...POS[n.id]); if (n.id !== "gate") g.scale.setScalar(1.2);
    /* Each region has its own cut, so it can be told apart without its colour. */
    const SHAPE = { senses: () => new THREE.IcosahedronGeometry(.6, 0), forward: () => new THREE.DodecahedronGeometry(.56, 0), triage: () => new THREE.OctahedronGeometry(.62, 0), workspace: () => new THREE.IcosahedronGeometry(.52, 1),
      packs: () => new THREE.TetrahedronGeometry(.72, 0), memory: () => new THREE.IcosahedronGeometry(.46, 1), sleep: () => new THREE.DodecahedronGeometry(.42, 0), team: () => new THREE.IcosahedronGeometry(.5, 0), twin: () => new THREE.OctahedronGeometry(.7, 0) };
    let core;
    if (n.id === "gate") core = new THREE.Group();
    else if (n.id === "reflex") { core = gem(new THREE.ConeGeometry(.55, 1.5, 5, 1), COLOR.bone); core.rotation.x = Math.PI; }
    else core = gem(SHAPE[n.id](), COLOR.bone);
    g.add(core);
    const heart = solid(new THREE.SphereGeometry(n.id === "gate" ? .13 : .15, 16, 12), COLOR.steel);
    const halo = glowSprite(COLOR.ember, 3); g.add(halo, heart);
    const o = { id: n.id, group: g, baseY: g.position.y, core, heart, halo, level: 0, rest: .1, fired: -99, seats: [], orbs: [], rings: [], extra: {} };
    accessories(o); groups.brain.add(g); nodes.set(n.id, o);
    const lab = document.createElement("div"); lab.className = `nlab n-${n.id}`;
    lab.innerHTML = `<div class="nm"><b></b><i></i></div><div class="v"></div><div class="sb"></div>`;
    lab.querySelector("b").textContent = n.name; lab.querySelector("i").textContent = n.who;
    labelLayer.append(lab); o.label = lab;
  }
  gate.group = nodes.get("gate").group;
  for (const [from, to, kind, tag] of EDGES) {
    const a = V(...POS[from]), b = V(...POS[to]), mid = a.clone().lerp(b, .5);
    const pts = [a];
    if (kind === "slow") { const side = V(0, 0, -1); pts.push(a.clone().lerp(b, .3).add(side.clone().multiplyScalar(1.6)).add(V(0, .8, 0)), mid.clone().add(side.clone().multiplyScalar(2.2)).add(V(0, .6, 0)), a.clone().lerp(b, .72).add(side.clone().multiplyScalar(1.2)).add(V(0, .3, 0))); }
    else if (kind === "plain") pts.push(mid.clone().add(V(0, tag === "learned" ? -.8 : .6, tag === "learned" ? .8 : -.5)));
    pts.push(b);
    const curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", .5), length = curve.getLength();
    const radius = kind === "fast" ? .075 : kind === "slow" ? .05 : .028;
    const mat = edgeMaterial(kind === "fast" ? COLOR.bone : kind === "slow" ? COLOR.ember : COLOR.steel, kind === "slow" ? length / .42 : 0, kind === "plain" ? .55 : .9);
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 72, radius, 6, false), mat); groups.brain.add(mesh);
    /* A wider, fainter copy of the path stands in for bloom, which on some graphics drivers drew the left of the screen black. */
    const shell = new THREE.Mesh(new THREE.TubeGeometry(curve, 72, radius * 3.4, 6, false), edgeMaterial(kind === "fast" ? COLOR.bone : kind === "slow" ? COLOR.ember : COLOR.steel, kind === "slow" ? length / .42 : 0, kind === "plain" ? .1 : .16)); groups.brain.add(shell);
    edges.set(`${from}>${to}`, { key: `${from}>${to}`, from, to, kind, curve, mesh, mat, shell, energy: 0, dur: kind === "fast" ? .5 : kind === "slow" ? 1.7 : .85, color: kind === "slow" ? COLOR.ember : COLOR.bone });
  }
  /* Everything inside the brain draws between the far wall of the glass and the near one. */
  for (const child of groups.brain.children) if (child !== shell.glass.group) child.traverse(o => { o.renderOrder = 2; });
}

function accessories(o) {
  const { group: g } = o;
  switch (o.id) {
    case "workspace": for (const dx of [-.8, .8]) { const r = new THREE.Mesh(new THREE.TorusGeometry(.42, .04, 8, 40), new THREE.MeshBasicMaterial({ color: COLOR.steelDim, transparent: true })); r.position.set(dx, -.05, 0); g.add(r); o.seats.push(r); } break;
    case "packs": for (let i = 0; i < 6; i++) { const a = Math.PI + (i / 5) * Math.PI, orb = solid(new THREE.SphereGeometry(.17, 12, 8), COLOR.steelDim); orb.position.set(Math.cos(a) * 1.3, -Math.sin(a) * .5 + .15, 0); orb.visible = false; g.add(orb); o.orbs.push(orb); } break;
    case "team": for (let i = 0; i < 3; i++) { const orb = solid(new THREE.SphereGeometry(.15, 12, 8), COLOR.ember); g.add(orb); o.orbs.push(orb); } break;
    case "memory": for (let i = 0; i < 12; i++) { const r = new THREE.Mesh(new THREE.TorusGeometry(.5 + i * .075, .012, 6, 48), new THREE.MeshBasicMaterial({ color: COLOR.ember, transparent: true, opacity: 0 })); r.rotation.x = 1.2; r.position.y = -.2; g.add(r); o.rings.push(r); } break;
    case "sleep": { const c = new THREE.Mesh(new THREE.TorusGeometry(.8, .07, 8, 40, Math.PI * 1.35), new THREE.MeshBasicMaterial({ color: COLOR.steel, transparent: true, opacity: .55 })); c.rotation.z = 2.3; g.add(c); o.extra.crescent = c; break; }
    case "gate": {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(9.2, .1, .1), new THREE.MeshBasicMaterial({ color: COLOR.bone, transparent: true, opacity: .8 })); o.core.add(bar); o.extra.bar = bar;
      for (const dx of [-4.6, 4.6]) { const post = new THREE.Mesh(new THREE.BoxGeometry(.1, .75, .1), new THREE.MeshBasicMaterial({ color: COLOR.bone, transparent: true, opacity: .8 })); post.position.set(dx, .32, 0); o.core.add(post); }
      break;
    }
    case "triage": for (let i = 0; i < 6; i++) { const pin = solid(new THREE.BoxGeometry(.08, .7, .08), COLOR.red); pin.position.set(-1.15 + i * .46, -.1, 0); pin.visible = false; g.add(pin); o.orbs.push(pin); } break;
    case "forward": { const spark = glowSprite(COLOR.red, 1.4); spark.visible = false; g.add(spark); o.extra.spark = spark; break; }
  }
}
function bump(id, size = 5) {
  const o = nodes.get(id); if (!o) return;
  o.level = 1; o.fired = clock.t; burst(o.group.position, id === "gate" ? COLOR.ember : COLOR.bone, size, .9);
  for (const other of nodes.values()) other.label.classList.toggle("lit", other === o);  /* the page shows only the region that just acted */
  o.label.classList.remove("flash"); void o.label.offsetWidth; o.label.classList.add("flash");
}
function emit(key) {
  const e = edges.get(key); if (!e) return false;
  if (signals.length >= MAXSIG) signals.shift();
  signals.push({ edge: e, t0: clock.t, color: col(e.color), size: e.kind === "fast" ? .6 : .46 });
  e.energy = 1; return true;
}

/* Dust and the signals that travel along curves. */
function buildAir() {
  const g = pointsGeometry(MAXDUST), r = rng(7);
  dustPoints = new THREE.Points(g, glowMaterial(1)); dustPoints.frustumCulled = false;
  dustPoints.userData.v = [];
  for (let i = 0; i < MAXDUST; i++) {
    setPoint(g, i, V(lerp(-18, 18, r()), lerp(-1, 15, r()), lerp(-9, 9, r())), lerp(.05, .14, r()), lerp(.12, .4, r()), col(r() > .7 ? COLOR.ember : COLOR.steel), r());
    dustPoints.userData.v.push([lerp(-.05, .05, r()), lerp(.01, .06, r()), lerp(-.03, .03, r())]);
  }
  groups.air.add(dustPoints);
}
function buildSignals() {
  signalPoints = new THREE.Points(pointsGeometry(MAXSIG * (trailLen + 1) + 64), glowMaterial(0)); signalPoints.frustumCulled = false; signalPoints.renderOrder = 6; groups.live.add(signalPoints);
  for (let i = 0; i < 28; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTexture, color: COLOR.bone, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
    s.visible = false; s.renderOrder = 6; s.userData = { t0: -9, dur: 1, size: 4 }; groups.live.add(s); rings.push(s);
  }
}
function burst(position, color, size = 4.5, dur = 1) {
  if (reducedMotion) return;
  const s = rings.find(r => !r.visible) || rings[0];
  s.position.copy(position); s.material.color.set(color); s.userData = { t0: clock.t, dur, size }; s.visible = true;
}
/* A comet along a lifted curve between two points: the decision rising to the Gate, the action falling to the city. */
function comet(from, to, color, dur = 1.1, lift = 2.2) {
  if (reducedMotion) return;
  const mid = from.clone().lerp(to, .5).add(V(0, lift, 0));
  if (signals.length >= MAXSIG) signals.shift();
  signals.push({ edge: { curve: new THREE.CatmullRomCurve3([from.clone(), mid, to.clone()]), dur, kind: "fast" }, t0: clock.t, color: col(color), size: .6, onEnd: () => burst(to, color, 3.4, .9) });
}

/* ---------------------------------------------------------------- the projector */
/* A plan of the city seen from straight above, drawn every frame into a small target. It holds only light: pools, rings and lines in
   the same x and z as the city. The model and its plate read it, which is what makes a mark land on matter. */
const PLAN = { x0: -32, x1: 32, z0: -18, z1: 22 };
const planUv = `vec2 planUv(vec2 p) { return vec2((p.x - (${PLAN.x0.toFixed(1)})) / ${(PLAN.x1 - PLAN.x0).toFixed(1)}, 1.0 - (p.y - (${PLAN.z0.toFixed(1)})) / ${(PLAN.z1 - PLAN.z0).toFixed(1)}); }`;
const plan = { scene: new THREE.Scene(), camera: null, target: null, pings: [] };
function planMark(geometry, color, map) {
  const m = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, map: map || null, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0; plan.scene.add(m); return m;
}
const planRing = (color, inner = .94) => planMark(new THREE.RingGeometry(inner, 1, 56), color);
const planPool = (color, radius) => { const m = planMark(new THREE.PlaneGeometry(2, 2), color, glowTexture); m.scale.set(radius, radius, 1); return m; };
function buildPlan() {
  const { x0, x1, z0, z1 } = PLAN, hw = (x1 - x0) / 2, hh = (z1 - z0) / 2;
  plan.camera = new THREE.OrthographicCamera(-hw, hw, hh, -hh, .1, 100);
  plan.camera.position.set((x0 + x1) / 2, 50, (z0 + z1) / 2); plan.camera.up.set(0, 0, -1); plan.camera.lookAt((x0 + x1) / 2, 0, (z0 + z1) / 2);
  plan.target = new THREE.WebGLRenderTarget(quality === "high" ? 1024 : 640, quality === "high" ? 640 : 400, { depthBuffer: false });
  for (let i = 0; i < 24; i++) { const r = planRing(COLOR.bone, .86); r.visible = false; r.userData = { t0: -9 }; plan.pings.push(r); }
}
/* A reading lands: one ring where it was sensed. */
function ping(p, color, size = 2.4) {
  if (reducedMotion || !p) return;
  const r = plan.pings.find(x => !x.visible) || plan.pings[0];
  r.position.x = p.x; r.position.z = p.z; r.material.color.set(color); r.userData = { t0: clock.t, size }; r.visible = true;
}

/* ---------------------------------------------------------------- the city */
const HEX = 2.7;
const hexAt = (cx, cz, r) => Array.from({ length: 6 }, (_, i) => [cx + Math.cos(i / 6 * Math.PI * 2) * r, cz + Math.sin(i / 6 * Math.PI * 2) * r]);
const insideHex = (dx, dz, r) => { const x = Math.abs(dx), z = Math.abs(dz); return z < r * .866 && x + z * .577 < r; };
const city = { key: "", zones: new Map(), labels: new Map(), group: null, roads: [], focus: null, extra: null };
function zoneKey(topo) { return topo ? topo.zones.map(z => `${z.id}:${z.x}:${z.y}`).join("|") : ""; }

function layoutZones(topo) {
  const zones = topo.zones, hasXY = zones.every(z => z.x != null && z.y != null);
  const raw = zones.map((z, k) => { const a = 2 * Math.PI * k / zones.length; return hasXY ? [z.x, z.y] : [1 + Math.cos(a), 1 + Math.sin(a)]; });
  const xs = raw.map(p => p[0]), ys = raw.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  return new Map(zones.map((z, k) => {
    const u = x1 === x0 ? .5 : (raw[k][0] - x0) / (x1 - x0), v = y1 === y0 ? .5 : (raw[k][1] - y0) / (y1 - y0);
    return [z.id, V(lerp(-13, 13, u), 0, lerp(-4, 11.5, v))];
  }));
}

/* The plate as a picture, painted once: the districts and roads inlaid, and each building's soft shadow, thrown away from the key light. */
const KEY = [-.45, .75, .5];
function paintPlate(topo, roads, boxes) {
  const size = quality === "high" ? 2048 : 1024, { x0, x1, z0, z1 } = PLAN, k = size / (x1 - x0);
  const c = document.createElement("canvas"); c.width = size; c.height = Math.round((z1 - z0) * k);
  const g = c.getContext("2d"), X = x => (x - x0) * k, Z = z => (z - z0) * k;
  g.fillStyle = "#10161d"; g.fillRect(0, 0, c.width, c.height);
  g.lineCap = "butt"; g.strokeStyle = "#2c3744"; g.lineWidth = .62 * k; g.beginPath();
  for (const r of roads) { g.moveTo(X(r.a.x), Z(r.a.z)); g.lineTo(X(r.b.x), Z(r.b.z)); }
  g.stroke();
  g.strokeStyle = "#64717f"; g.lineWidth = .03 * k; g.setLineDash([.22 * k, .22 * k]); g.beginPath();
  for (const r of roads) { g.moveTo(X(r.a.x), Z(r.a.z)); g.lineTo(X(r.b.x), Z(r.b.z)); }
  g.stroke(); g.setLineDash([]);
  for (const z of topo.zones) {
    const p = city.zones.get(z.id), hex = hexAt(p.x, p.z, HEX);
    g.beginPath(); hex.forEach(([x, y], i) => (i ? g.lineTo(X(x), Z(y)) : g.moveTo(X(x), Z(y)))); g.closePath();
    g.fillStyle = "#222c37"; g.fill(); g.strokeStyle = "#8a99a8"; g.lineWidth = .05 * k; g.stroke();
  }
  g.globalCompositeOperation = "multiply";
  for (const [blur, alpha, stretch] of [[.34, .5, 1], [.12, .75, 0]]) {
    g.filter = `blur(${(blur * k).toFixed(1)}px)`; g.strokeStyle = `rgba(0,0,0,${alpha})`;
    for (const b of boxes) {
      g.lineWidth = Math.min(b.w, b.d) * k; g.beginPath();
      const dx = -KEY[0] / KEY[1] * b.h * stretch * .8, dz = -KEY[2] / KEY[1] * b.h * stretch * .8;
      g.moveTo(X(b.x), Z(b.z)); g.lineTo(X(b.x + dx) + .01, Z(b.z + dz)); g.stroke();
    }
  }
  g.filter = "none"; g.globalCompositeOperation = "source-over";
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy(); return t;
}

function buildCity(topo) {
  if (city.group) { groups.city.remove(city.group); city.group.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.uniforms && o.material.uniforms.uMap && o.material.uniforms.uMap.value.dispose(); }); }
  for (const l of city.labels.values()) l.remove();
  city.labels.clear(); city.zones = layoutZones(topo); city.roads = []; trafficPoints = null;
  const group = new THREE.Group(); city.group = group; groups.city.add(group);
  const high = quality === "high";

  /* Streets in a grid inside each district, lots along them, the tall ones near the middle and with a setback on top. */
  const boxes = [], lot = high ? .56 : .78, block = high ? 3 : 2, near = [];
  for (const z of topo.zones) {
    const centre = city.zones.get(z.id), r = rng(hash(z.id)), tall = .75 + (hash(z.name) % 60) / 100, n = Math.ceil(HEX / lot);
    for (let ix = -n; ix <= n; ix++) for (let iz = -n; iz <= n; iz++) {
      const dx = (ix + Math.floor(ix / block) * .34) * lot, dz = (iz + Math.floor(iz / block) * .34) * lot, jitter = r();
      if (!insideHex(dx, dz, HEX * .9) || jitter < .16) continue;
      const w = lot * lerp(.62, .92, r()), d = lot * lerp(.62, .92, r()), far = Math.hypot(dx, dz) / HEX;
      const h = (.2 + Math.pow(r(), 2.1) * 2.5 * (1 - .62 * far)) * tall, b = { x: centre.x + dx, z: centre.z + dz, w, d, h };
      boxes.push(b); near.push(b);
      if (h > 1.15) boxes.push({ x: b.x, z: b.z, w: w * .62, d: d * .62, h: h * 1.24 });
    }
  }
  /* A far skyline: a ring of low towers outside the districts, only where the machine can afford it. */
  if (high) {
    const r = rng(404);
    for (let i = 0; i < 70; i++) {
      const x = lerp(-32, 32, r()), zz = lerp(-18, -11, r()), w = lerp(.5, 1.3, r()), h = lerp(.6, 2.2, Math.pow(r(), 1.8));
      boxes.push({ x, z: zz, w, d: lerp(.5, 1.3, r()), h });
    }
  }

  /* Roads between neighbouring districts, from the edge of one to the edge of the other. */
  const roads = [];
  for (const [a, b] of topo.adjacency) {
    const pa = city.zones.get(a), pb = city.zones.get(b); if (!pa || !pb) continue;
    const inset = HEX * .82 / pa.distanceTo(pb);
    roads.push({ a: pa.clone().lerp(pb, inset), b: pa.clone().lerp(pb, 1 - inset) });
  }
  city.roads = roads;

  const plate = new THREE.Mesh(new THREE.PlaneGeometry(PLAN.x1 - PLAN.x0, PLAN.z1 - PLAN.z0), new THREE.ShaderMaterial({
    uniforms: { uMap: { value: paintPlate(topo, roads, near) }, uProj: { value: plan.target.texture }, uHouse },
    vertexShader: `varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `varying vec3 vW; uniform sampler2D uMap; uniform sampler2D uProj; uniform float uHouse; ${planUv}
      void main() {
        vec2 uv = planUv(vW.xz), cell = vW.xz / 1.5, g = abs(fract(cell - 0.5) - 0.5) / fwidth(cell);
        float edge = 1.0 - smoothstep(0.55, 1.0, length((vW.xz - vec2(0.0, 2.5)) / vec2(31.0, 19.5)));
        vec3 c = texture2D(uMap, uv).rgb * (0.35 + 0.65 * uHouse) * 1.5 + vec3(0.09, 0.13, 0.19) * (1.0 - min(min(g.x, g.y), 1.0)) * 0.2;
        c += texture2D(uProj, uv).rgb * 1.6;
        gl_FragColor = vec4(c, edge); gl_FragColor = linearToOutputTexel(gl_FragColor);
      }`,
    transparent: true,  /* the plate dissolves into the sky behind it, whatever colour that is at that angle */
  }));
  plate.renderOrder = -5; plate.rotation.x = -Math.PI / 2; plate.position.set((PLAN.x0 + PLAN.x1) / 2, 0, (PLAN.z0 + PLAN.z1) / 2); group.add(plate);

  const model = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.ShaderMaterial({
    uniforms: { uProj: { value: plan.target.texture }, uHouse, uTime },
    vertexShader: `varying vec3 vW; varying vec3 vN; varying vec3 vL;
      void main() { vL = position; vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0); vW = w.xyz; vN = normal; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `varying vec3 vW; varying vec3 vN; varying vec3 vL; uniform sampler2D uProj; uniform float uHouse; uniform float uTime; ${planUv}
      float cellHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      void main() {
        vec3 n = normalize(vN), albedo = vec3(0.74, 0.76, 0.74);
        float key = max(dot(n, normalize(vec3(${KEY.join(", ")}))), 0.0), sky = 0.5 + 0.5 * n.y, ao = mix(0.34, 1.0, smoothstep(0.0, 1.0, vW.y));
        vec3 c = albedo * (0.035 + 0.25 * key + 0.07 * sky) * ao * (0.3 + 0.7 * uHouse);
        vec3 e = abs(vL); float mid = max(min(e.x, e.y), min(max(e.x, e.y), e.z)); c += vec3(0.075) * smoothstep(0.5 - fwidth(mid) * 1.4, 0.5, mid) * uHouse;
        vec2 grid = vec2(vW.y * 5.5, (vW.x + vW.z) * 5.5), f = fract(grid), id = floor(grid);
        float pane = step(0.24, f.x) * step(f.x, 0.76) * step(0.2, f.y) * step(f.y, 0.8), far = smoothstep(0.35, 1.0, fwidth(grid.x));
        float on = step(0.76, cellHash(id)) * (0.55 + 0.45 * sin(uTime * 0.3 + cellHash(id + 3.0) * 40.0));
        c += vec3(1.0, 0.68, 0.36) * mix(pane, 0.32, far) * on * (1.0 - abs(n.y)) * 0.5 * (0.45 + 0.55 * uHouse);
        vec3 light = texture2D(uProj, planUv(vW.xz)).rgb;
        c += light * albedo * (0.42 + 0.58 * max(dot(n, normalize(vec3(-0.2, 1.0, 0.3))), 0.0)) * 2.6;
        float out_ = smoothstep(18.0, 27.0, length((vW.xz - vec2(0.0, 2.5)) * vec2(1.0, 1.45)));
        gl_FragColor = vec4(mix(c, vec3(0.0042, 0.0070, 0.0115), out_), 1.0); gl_FragColor = linearToOutputTexel(gl_FragColor);
      }`,
  }), boxes.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion();
  boxes.forEach((b, i) => { m.compose(V(b.x, b.h / 2, b.z), q, V(b.w, b.h, b.d)); model.setMatrixAt(i, m); });
  model.frustumCulled = false; group.add(model);

  /* Traffic: ambient vehicles on every road. They are scenery (the Twin sends no vehicle positions), so they stay dim. */
  if (high && city.roads.length) {
    const n = city.roads.length * 7, tg = pointsGeometry(n), tr = rng(77);
    trafficPoints = new THREE.Points(tg, glowMaterial(0)); trafficPoints.frustumCulled = false;
    trafficPoints.userData.cars = Array.from({ length: n }, (_, i) => ({ road: Math.floor(i / 7), u: tr(), v: lerp(.04, .1, tr()) * (tr() > .5 ? 1 : -1), lane: tr() > .5 ? .13 : -.13, warm: tr() > .45 }));
    group.add(trafficPoints);
  }

  /* The focus ring: where the camera is looking, thrown on the model by the projector. */
  if (city.focus) { plan.scene.remove(city.focus); city.focus.geometry.dispose(); }
  city.focus = planMark(new THREE.RingGeometry(HEX * 1.04, HEX * 1.12, 6), COLOR.bone);

  for (const z of topo.zones) {
    const l = document.createElement("div"); l.className = "zlab"; l.innerHTML = `<b></b><i></i>`; l.firstChild.textContent = z.name; labelLayer.append(l); city.labels.set(z.id, l);
  }
}

/* ---------------------------------------------------------------- what is happening in the city */
const live = { incidents: new Map(), units: new Map(), suspects: new Map(), beacons: new Map(), fences: new Map(), seen: new Set(), trail: null };
const ROOFS = 3;  /* markers ride above the tallest roofs */

function ensureLive(s) {
  if (!city.group) return;
  const pos = id => city.zones.get(id);
  const open = new Set([...s.incidents.values()].filter(i => i.status === "open").map(i => i.zone));
  for (const id of open) if (!live.incidents.has(id) && pos(id)) {
    const p = pos(id), grp = new THREE.Group(); grp.position.copy(p);
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(.04, .3, 6, 12, 1, true), new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uOpacity: { value: .6 }, uColor: { value: col(COLOR.red) } },
      vertexShader: `varying float vH; void main() { vH = uv.y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `varying float vH; uniform float uOpacity; uniform vec3 uColor; void main() { gl_FragColor = vec4(uColor * 1.6, uOpacity * pow(1.0 - vH, 1.6)); gl_FragColor = linearToOutputTexel(gl_FragColor); }`,
    })); beam.position.y = 3;
    const rim = [0, 1].map(() => { const r = planRing(COLOR.red, .9); r.position.set(p.x, 0, p.z); return r; }), pool = planPool(COLOR.red, HEX * 1.25); pool.position.set(p.x, 0, p.z);
    grp.add(beam); groups.live.add(grp); live.incidents.set(id, { grp, beam, rim, pool, born: clock.t });
    burst(p.clone().setY(.2), COLOR.red, 7, 1.4);
  }
  for (const [id, o] of live.incidents) if (!open.has(id)) { groups.live.remove(o.grp); for (const m of [...o.rim, o.pool]) plan.scene.remove(m); live.incidents.delete(id); }

  const held = s.held;
  for (const id of held) if (!live.fences.has(id) && pos(id)) {
    const seg = [], N = 36, R = HEX * .98, top = 1.3;
    for (let i = 0; i < N; i++) {
      const a = i / N * Math.PI * 2, b = (i + 1) / N * Math.PI * 2, x0 = Math.cos(a) * R, z0 = Math.sin(a) * R, x1 = Math.cos(b) * R, z1 = Math.sin(b) * R;
      seg.push(x0, .04, z0, x1, .04, z1, x0, top, z0, x1, top, z1);
      if (i % 2 === 0) seg.push(x0, .04, z0, x0, top, z0);
    }
    const fg = new THREE.BufferGeometry(); fg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
    const f = new THREE.LineSegments(fg, new THREE.LineBasicMaterial({ color: COLOR.ember, transparent: true, opacity: .7, blending: THREE.AdditiveBlending }));
    f.position.copy(pos(id)); f.renderOrder = 3; groups.live.add(f); live.fences.set(id, f);
    f.userData.pool = planPool(COLOR.ember, HEX * 1.15); f.userData.pool.position.set(pos(id).x, 0, pos(id).z);
  }
  for (const [id, f] of live.fences) if (!held.has(id)) { groups.live.remove(f); plan.scene.remove(f.userData.pool); live.fences.delete(id); }

  for (const u of s.units.values()) if (!live.units.has(u.id) && pos(u.zone)) {
    const pursuit = u.mode === "pursuit", body = new THREE.Group();
    const cone = pursuit ? solid(new THREE.ConeGeometry(.3, .8, 4), COLOR.bone) : wire(new THREE.ConeGeometry(.3, .8, 4), COLOR.bone, 1);
    const halo = glowSprite(COLOR.bone, 1.1); halo.material.opacity = .4;
    body.add(cone, halo); body.position.copy(gatePos).add(V(0, -.3, 0)); groups.live.add(body);
    const lab = document.createElement("div"); lab.className = "ulab"; lab.textContent = u.id.replace(/^unit-/, ""); labelLayer.append(lab);
    live.units.set(u.id, { body, born: clock.t, from: body.position.clone(), lab, zone: u.zone, n: 0 });
    burst(pos(u.zone).clone().setY(.2), COLOR.bone, 4, 1);
  }
  for (const [id, o] of live.units) if (!s.units.has(id)) { groups.live.remove(o.body); o.lab.remove(); live.units.delete(id); }
  const stack = new Map();
  for (const u of s.units.values()) { const o = live.units.get(u.id); if (!o || !pos(u.zone)) continue; o.zone = u.zone; const n = stack.get(u.zone) || 0; stack.set(u.zone, n + 1); o.n = n; o.state = u.state; o.mode = u.mode; }

  for (const id of s.alerts) if (!live.beacons.has(id) && pos(id)) {
    const body = glowSprite(COLOR.ember, 1.5); body.position.copy(gatePos); groups.live.add(body);
    const rim = [0, 1, 2].map(() => { const r = planRing(COLOR.ember, .92); r.position.set(pos(id).x, 0, pos(id).z); return r; });
    live.beacons.set(id, { body, rim, born: clock.t, from: gatePos.clone() });
  }
  for (const [id, o] of live.beacons) if (!s.alerts.has(id)) { groups.live.remove(o.body); o.rim.forEach(r => plan.scene.remove(r)); live.beacons.delete(id); }

  /* A suspect's trail, and the suspects themselves. */
  for (const sus of s.suspects.values()) if (sus.level !== "none" && !live.suspects.has(sus.id) && pos(sus.zone)) {
    const m = sus.level === "suspect" ? solid(new THREE.OctahedronGeometry(.36, 0), COLOR.red) : wire(new THREE.OctahedronGeometry(.36, 0), COLOR.red, 1);
    m.position.copy(pos(sus.zone)).add(V(-1.3, ROOFS, 0)); groups.live.add(m);
    const lab = document.createElement("div"); lab.className = "ulab sus"; lab.textContent = sus.id; labelLayer.append(lab);
    live.suspects.set(sus.id, { m, lab, id: sus.id });
  }
  for (const [id, o] of live.suspects) { const sus = s.suspects.get(id); if (!sus || sus.level === "none") { groups.live.remove(o.m); o.lab.remove(); live.suspects.delete(id); } }
  /* The suspect's trail is thrown on the model: a bar of light from zone to zone. */
  if (live.trail) { plan.scene.remove(live.trail); live.trail.geometry.dispose(); live.trail = null; }
  const bars = [];
  for (const sus of s.suspects.values()) {
    const pts = (sus.trail || []).map(pos).filter(Boolean);
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], len = Math.hypot(b.x - a.x, b.z - a.z) || 1, nx = -(b.z - a.z) / len * .16, nz = (b.x - a.x) / len * .16;
      bars.push(a.x + nx, 0, a.z + nz, b.x + nx, 0, b.z + nz, b.x - nx, 0, b.z - nz, a.x + nx, 0, a.z + nz, b.x - nx, 0, b.z - nz, a.x - nx, 0, a.z - nz);
    }
  }
  if (bars.length) {
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(bars, 3));
    live.trail = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: COLOR.red, transparent: true, opacity: .7, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false, side: THREE.DoubleSide }));
    plan.scene.add(live.trail);
  }

  /* New strings announce themselves with a flash where they land. */
  const targets = [...[...s.units.keys()].map(k => "u:" + k), ...[...s.alerts].map(k => "a:" + k)];
  for (const t of targets) if (!live.seen.has(t)) { live.seen.add(t); bump("gate", 4); }
  for (const t of [...live.seen]) if (!targets.includes(t)) live.seen.delete(t);
}

const lineGeo = () => { const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(24 * 3), 3)); return g; };
let stringLines = [];
function stringTargets() {
  const out = [];
  for (const [id, o] of live.units) out.push({ key: "u:" + id, at: o.body.position });
  for (const [id, o] of live.beacons) out.push({ key: "a:" + id, at: o.body.position });
  return out.sort((a, b) => a.at.x - b.at.x);
}
function drawStrings() {
  const targets = stringTargets();
  while (stringLines.length < targets.length) {
    const l = new THREE.Line(lineGeo(), new THREE.LineBasicMaterial({ color: COLOR.ember, transparent: true, opacity: .75, blending: THREE.AdditiveBlending })); l.frustumCulled = false; groups.live.add(l); stringLines.push(l);
  }
  stringLines.forEach((l, i) => {
    l.visible = i < targets.length; if (!l.visible) return;
    const t = targets[i], hx = gatePos.x + (targets.length === 1 ? 0 : lerp(-4.2, 4.2, i / (targets.length - 1))), a = V(hx, gatePos.y, gatePos.z), b = t.at, pos = l.geometry.attributes.position;
    for (let k = 0; k < 24; k++) {
      const u = k / 23, sway = reducedMotion ? 0 : Math.sin(clock.t * .9 + i * 1.7 + u * 3.2) * .16 * Math.sin(Math.PI * u) * (1 - calm * .6);
      pos.setXYZ(k, lerp(a.x, b.x, u) + sway, lerp(a.y, b.y, u) - Math.sin(Math.PI * u) * .12, lerp(a.z, b.z, u) + sway * .6);
    }
    pos.needsUpdate = true;
  });
}

/* ---------------------------------------------------------------- the director */
/* An event becomes a shot: where the camera goes, one caption, how long it stays. The queue is short on purpose: in a burst the
   least important shots are dropped and the camera cuts to the overview, so it never whips around. */
const OVERVIEW = { kind: "overview", pos: V(1.5, 21, 45.5), look: V(1.5, 5.7, 3) };
const ALONE = { kind: "overview", pos: V(1.5, 12.5, 36), look: V(1.5, 9.2, 0) };
const dir = { queue: [], cur: null, target: OVERVIEW, focus: null, until: 0, paused: false, free: false, pos: OVERVIEW.pos.clone(), look: OVERVIEW.look.clone(), orbit: { yaw: 0, pitch: .32, dist: 45 } };
const MIN_DWELL = 1.1, MAX_QUEUE = 4;
/* A thought replayed: the steps of an explanation, one shot per run of steps in the same region, in the order they happened. The
   region lights, a signal runs along the real paths from the one before, and one caption says what happened there. */
const thought = { steps: null, i: 0, at: 0, prev: null, held: false };
const LAYER = { twin: "Twin", guardian: "Guardian", brain: "Brain" };
/* The paths between two regions, by the page's own edge list (breadth first, the way an event really travels). */
function routeBetween(a, b) {
  const next = new Map(); for (const [from, to] of EDGES) { if (!next.has(from)) next.set(from, []); next.get(from).push(to); }
  const seen = new Map([[a, null]]), queue = [a];
  while (queue.length) {
    const at = queue.shift(); if (at === b) break;
    for (const to of next.get(at) || []) if (!seen.has(to)) { seen.set(to, at); queue.push(to); }
  }
  if (!seen.has(b)) return [];
  const keys = []; for (let at = b; seen.get(at) != null; at = seen.get(at)) keys.unshift(`${seen.get(at)}>${at}`);
  return keys;
}
function thoughtTick() {
  if (clock.t < thought.at) return;
  const group = thought.steps[thought.i];
  if (!group) return endThought();
  const last = ++thought.i === thought.steps.length, first = group.items[0], facts = group.items.slice(0, 2).map(x => x.fact).join(" ");
  const words = facts.split(/\s+/).length, dwell = first.tour ? clamp(2 + words * .24, 4, 10) : clamp(1.5 + words * .1, 2.2, 5), name = (NODES.find(n => n.id === group.region) || {}).name || group.region;
  /* The tour keeps the whole brain in frame and leans toward the part, so the jury sees where it sits. */
  const at = V(...POS[group.region]), cam = first.tour ? { pos: V(at.x * .4 + 3, at.y * .35 + 8, 35), look: V(at.x * .3 + 3, at.y * .5 + 3.4, 0) } : regionCam(group.region);
  thought.part = first.tour ? group.region : null;
  stage.classList.toggle("touring", !!first.tour);
  for (const n of nodes.values()) n.label.classList.toggle("focus", n.id === thought.part);
  startShot({ pri: 9, dwell, cam, legs: [{ cam, hold: dwell }], head: first.head || ((LAYER[first.layer] || first.layer) === name ? name : `${LAYER[first.layer] || first.layer} \u00b7 ${name}`),
    sub: state ? names(state, facts) : facts, tone: first.tour ? "tour" : last ? (thought.held ? "held" : "good") : "", time: first.at_ms, t0: 0, tag: first.tag, kind: "thought" });
  window.dispatchEvent(new CustomEvent("thoughtstep", { detail: group.region }));
  if (!reducedMotion && thought.prev && thought.prev !== group.region) for (const key of routeBetween(thought.prev, group.region)) emit(key);
  bump(group.region, 5);
  if (last && thought.held) burst(gatePos.clone().add(V(0, -.3, 0)), COLOR.red, 6, 1.5);
  thought.prev = group.region; thought.at = clock.t + dwell + (last ? 1.5 : .15);
}
function endThought() {
  thought.part = null; stage.classList.remove("touring"); for (const n of nodes.values()) n.label.classList.remove("focus");
  thought.steps = null; dir.cur = null; dir.target = OVERVIEW; dir.focus = null; capEl.classList.remove("on");
  window.dispatchEvent(new Event("thoughtend"));
}
function startThought(explanation) {
  const groups = [];
  for (const st of explanation.steps || []) { const tail = groups[groups.length - 1]; if (tail && tail.region === st.region) tail.items.push(st); else groups.push({ region: st.region, items: [st] }); }
  if (!groups.length) return false;
  dir.queue.length = 0; dir.paused = false; dir.free = false;
  Object.assign(thought, { steps: reducedMotion ? [groups[groups.length - 1]] : groups, i: 0, at: clock.t, prev: null, held: explanation.subject === "held" });
  return true;
}
const WORD = { held: "Held · ", incident: "Incident · ", warning: "Doubted · ", critical: "Not trusted · ", crew: "Team · " };
const zoneOf = id => city.zones.get(id);
const num3 = v => Number(Number(v).toPrecision(3));

function regionCam(id) { const p = V(...POS[id]); return { pos: p.clone().add(V(-2.6, 2.4, 14)), look: p.clone().add(V(.6, -.6, 0)) }; }
const leg = (id, hold) => ({ cam: regionCam(id), hold });
/* The zone sits low in the frame and the Gate and the regions that acted hang above it: the Brain is never out of sight. */
function closeOn(p) { const c = V(p.x * .6, 0, p.z * .55); return { pos: c.clone().add(V(1.2, 13.5, 27)), look: c.clone().add(V(0, 5.6, -2.2)) }; }
function riseOn(p) { const c = V(p.x * .6, 0, p.z * .55); return { pos: c.clone().add(V(3.5, 16, 32)), look: c.clone().add(V(0, 6, -2.5)) }; }

function shotFor(e, s) {
  const d = e.data || {}, name = id => zoneName(s, id), c = s.c;
  const at = id => zoneOf(id);
  switch (e.type) {
    case "brain.incident.opened": {
      const p = at(d.zone_id); if (!p) return null;
      return { pri: 4, dwell: 2, zone: d.zone_id, cam: riseOn(p), legs: [leg("triage", .8), { cam: riseOn(p), hold: 1.4 }], head: "Incident opened", sub: `${INCIDENT[d.type] || d.type} in ${name(d.zone_id)}`, tone: "incident" };
    }
    case "brain.percept.surprise": {
      const z = c.sensorZone[d.sensor_id], p = z && at(z), [label] = FIELD[d.field] || [String(d.field || "value").replace(/_/g, " ")];
      const head = d.explained ? "Change expected: the Brain caused it" : d.recovered ? "Back to a level it had before" : d.kind === "neighbour" ? "Disputed by a partner sensor"
        : d.rebaselined ? "New normal accepted" : d.run > 1 ? "Surprising reading confirmed" : "Reading doubted";
      return { pri: 3, dwell: 1.7, zone: z, cam: p ? closeOn(p) : null, legs: p ? [leg("forward", .9), { cam: closeOn(p), hold: 1.0 }] : [leg("forward", 1.3)], head, sub: `${label} ${num3(d.observed)}, usually ${num3(d.expected)} · ${Number(d.z).toFixed(0)} spreads off`, tone: d.explained || d.recovered ? "good" : "warning" };
    }
    case "brain.verdict.received": {
      if (d.status === "trusted" || d.status === "unavailable") return null;  /* "unavailable" is said once, by brain.guardian.unavailable */
      const z = c.sensorZone[(e.subject || "").split("#")[0]], p = z && at(z);
      return { pri: 4, dwell: 1.8, zone: z, cam: p ? closeOn(p) : null, legs: p ? [leg("senses", .7), { cam: closeOn(p), hold: 1.1 }] : [leg("senses", 1.2)], head: `Guardian: ${d.status}`, sub: "the Brain will not act on this reading alone", tone: "critical" };
    }
    case "brain.reading.rejected": return { pri: 4, dwell: 1.6, head: "Reading refused at the door", sub: names(s, d.message || d.code || ""), tone: "critical" };
    case "brain.workspace.ignited": {
      const p = at(d.zone_id); if (!p) return null;
      return { pri: 2, dwell: 1.3, zone: d.zone_id, cam: closeOn(p), legs: [leg("workspace", .8), { cam: closeOn(p), hold: .7 }], head: d.slot === false ? `${e.subject} gets attention beyond the usual limit` : `${e.subject} gets the Brain's attention`, sub: `urgency ${Number(d.salience).toFixed(2)} · ${INCIDENT[d.type] || d.type} in ${name(d.zone_id)}`, tone: "" };
    }
    case "brain.deliberation.started": return { pri: 2, dwell: 1.4, cam: regionCam("team"), legs: [leg("team", 1.4)], head: "The team of agents is working", sub: "Analyst, Tactician and Chief, in turn", tone: "", keep: true };
    case "brain.decision.made": {
      const [head, sub] = describe(s, d.action, d.params || {}), z = (d.params || {}).zone_id, p = z && at(z);
      return { pri: 3, dwell: 1.9, zone: z, cam: p ? closeOn(p) : null, legs: [leg(d.tier === "reflex" ? "reflex" : "team", .7), leg("gate", .6), ...(p ? [{ cam: closeOn(p), hold: .8 }] : [])], head, sub: `${d.tier === "reflex" ? "Reflex" : "Team"} · ${sub}`, tone: d.tier === "reflex" ? "" : "crew", comet: p ? { to: p, color: d.tier === "reflex" ? COLOR.bone : COLOR.ember } : null };
    }
    case "brain.action.blocked": {
      const params = d.params || {}, z = params.zone_id || (s.incidents.get(e.subject) || {}).zone, p = z && at(z);
      const [what] = d.params ? describe(s, d.would_have, params) : [d.entity_id ? `Pursue ${d.entity_id}` : String(d.would_have || "act").replace(/_/g, " ")];
      return { pri: 5, dwell: 2.6, zone: z, cam: p ? closeOn(p) : null, legs: [leg("gate", 1.1), ...(p ? [{ cam: closeOn(p), hold: 1.5 }] : [])], head: `Held: ${CHECK[d.check] || d.check}`, sub: `Would ${what.charAt(0).toLowerCase()}${what.slice(1)}`, tone: "held", stamp: true };
    }
    case "brain.action.result": {
      const row = s.decisions.get(d.decision_id), z = row && row.params.zone_id, p = z && at(z);
      if (!row || !p || !["dispatched", "duplicate", "broadcast", "ok", "accepted"].includes(d.status)) return null;
      return { pri: 3, dwell: 1.6, zone: z, cam: p ? closeOn(p) : null, legs: [leg("twin", .7), { cam: closeOn(p), hold: .9 }], head: d.unit_id ? `${String(d.unit_id).replace(/^unit-/, "")} is on its way` : "The Twin answered", sub: `${describe(s, row.action, row.params)[0]}`, tone: "good", comet: { from: true, to: p, color: COLOR.bone } };
    }
    case "brain.guardian.unavailable": return { pri: 6, dwell: 2.6, cam: regionCam("senses"), legs: [leg("senses", 2.2)], head: "The Guardian has stopped answering", sub: "Only low-impact actions until it returns", tone: "critical" };
    case "brain.degraded": return { pri: 5, dwell: 2.2, cam: regionCam("twin"), legs: [leg("twin", 1.9)], head: "The Twin has stopped answering", sub: "The Brain keeps what it holds and tries again", tone: "critical" };
    case "brain.recovered": return { pri: 4, dwell: 1.8, cam: regionCam("twin"), legs: [leg("twin", 1.5)], head: "The Twin answers again", sub: "The Brain reads on from where it stopped", tone: "good" };
    case "brain.human.needed": return { pri: 5, dwell: 2.4, cam: regionCam("gate"), legs: [leg("gate", 2)], head: "A person is needed", sub: names(s, String(d.message || d.why || "the Brain cannot decide this alone").replace(/_/g, " ")), tone: "held" };
    case "brain.forecast.warned": {
      const p = at(d.zone_id); if (!p) return null;
      return { pri: 4, dwell: 2, zone: d.zone_id, cam: riseOn(p), legs: [leg("forward", .8), { cam: riseOn(p), hold: 1.2 }], head: "Water rising: an early warning", sub: `${name(d.zone_id)}, about ${Math.max(1, Math.round((d.seconds_to_threshold || 0) / 60))} min to the flood line`, tone: "incident" };
    }
    case "brain.plan.verified": return { pri: 3, dwell: 1.6, cam: regionCam("team"), legs: [leg("team", 1.4)], head: "The team's plan passes the code's checks", sub: String(d.option || "").replace(/-/g, " "), tone: "good" };
    case "brain.incident.closed": return { pri: 2, dwell: 1.7, cam: OVERVIEW, head: "Incident closed", sub: UNIT[d.outcome] || d.outcome, tone: "good" };
  }
  return null;
}

/* Shots of one kind that arrive together are one shot: "4 decisions" with their titles, not four cuts. */
const MERGE = { "brain.decision.made": n => `${n} decisions`, "brain.action.result": n => `${n} calls answered`, "brain.action.blocked": n => `${n} actions held`, "brain.percept.surprise": n => `${n} readings left their range` };
function enqueue(shot, e, s) {
  shot.time = Date.parse(e.time); shot.t0 = s.t0; shot.kind = e.type; shot.enq = clock.t; shot.titles = [shot.head];
  const tail = dir.queue[dir.queue.length - 1];
  if (tail && tail.kind === shot.kind && MERGE[shot.kind] && clock.t - tail.enq < .9) {
    tail.titles.push(shot.head); tail.enq = clock.t; tail.dwell = Math.min(2.6, tail.dwell + .3);
    tail.head = MERGE[shot.kind](tail.titles.length); tail.sub = tail.titles.join(" · ");
    if (tail.zone !== shot.zone) { tail.cam = OVERVIEW; tail.zone = null; }
    tail.pri = Math.max(tail.pri, shot.pri);
    return;
  }
  dir.queue.push(shot);
  while (dir.queue.length > MAX_QUEUE) {
    let drop = 0; for (let i = 1; i < dir.queue.length; i++) if (dir.queue[i].pri < dir.queue[drop].pri) drop = i;
    dir.queue.splice(drop, 1);
  }
}

function startShot(shot) {
  dir.cur = shot;
  if (shot.legs) {
    /* Behind in the story: skip the visit to the region and go straight to where it happened. */
    shot.run = dir.queue.length >= 2 ? shot.legs.slice(-1) : shot.legs; shot.leg = 0;
    dir.target = shot.run[0].cam; dir.legUntil = clock.t + shot.run[0].hold;
    shot.dwell = Math.max(MIN_DWELL, shot.run.reduce((a, l) => a + l.hold, 0) + .25);
  } else if (shot.cam) dir.target = shot.cam; else if (!shot.keep) dir.target = OVERVIEW;
  dir.until = clock.t + Math.max(MIN_DWELL, shot.dwell || MIN_DWELL);
  if (shot.head) {
    capEl.className = `shotcap on ${shot.tone || ""}`;
    capEl.querySelector("b").textContent = shot.head; capEl.querySelector("i").textContent = shot.sub || "";
    const tm = capEl.querySelector(".tm");
    tm.textContent = shot.tag || (shot.time != null && shot.t0 != null ? `+${((shot.time - shot.t0) / 1000).toFixed(2)} s` : "");
    tm.dataset.word = WORD[shot.tone] || "";
    void capEl.offsetWidth; capEl.classList.add("cut");
  }
  dir.focus = shot.zone && city.focus && zoneOf(shot.zone) && (!shot.run || shot.run.length === 1) ? zoneOf(shot.zone) : null;
  if (shot.comet) {
    const gateAt = gatePos.clone().add(V(0, -.3, 0));
    if (shot.comet.from) comet(gateAt, shot.comet.to.clone().add(V(0, 1.2, 0)), shot.comet.color, 1.2, 1.6);
    else comet(shot.comet.to.clone().add(V(0, .8, 0)), gateAt, shot.comet.color, 1.1, 2.6);
  }
  if (shot.stamp && shot.zone && zoneOf(shot.zone)) { burst(zoneOf(shot.zone).clone().setY(.3), COLOR.red, 6, 1.5); bump("gate", 5); }
}

function direct(dt) {
  if (dir.paused || dir.free) return;
  if (thought.steps) return thoughtTick();
  const c = dir.cur;
  if (c && c.run && c.leg < c.run.length - 1 && clock.t >= dir.legUntil) {
    c.leg++; dir.target = c.run[c.leg].cam; dir.legUntil = clock.t + c.run[c.leg].hold;
    if (c.leg === c.run.length - 1 && c.zone && zoneOf(c.zone)) dir.focus = zoneOf(c.zone);
  }
  if (clock.t >= dir.until) {
    const next = dir.queue.shift();
    if (next) startShot(next);
    else if (dir.cur && clock.t > dir.until + 3.5) { dir.cur = null; dir.target = OVERVIEW; dir.focus = null; capEl.classList.remove("on"); }
  }
}

/* The camera eases toward the shot; asleep, it pulls back and drifts. */
const camTarget = { pos: new THREE.Vector3(), look: new THREE.Vector3() };
function moveCamera(dt) {
  const t = clock.t;
  if (dir.free) {
    const o = dir.orbit, c = OVERVIEW.look;
    camTarget.pos.set(c.x + Math.sin(o.yaw) * Math.cos(o.pitch) * o.dist, c.y + Math.sin(o.pitch) * o.dist, c.z + Math.cos(o.yaw) * Math.cos(o.pitch) * o.dist);
    camTarget.look.copy(c);
  } else {
    const wide = calm > .5 || !dir.target ? OVERVIEW : dir.target, tgt = wide === OVERVIEW && !city.group ? ALONE : wide;  /* no city yet: the brain fills the frame */
    camTarget.pos.copy(tgt.pos); camTarget.look.copy(tgt.look);
    if (dir.cur && dir.cur.follow) { const u = live.units.get(dir.cur.follow); if (u) camTarget.look.copy(u.body.position); }
    if (wide === OVERVIEW) camTarget.pos.sub(camTarget.look).multiplyScalar(Math.max(1, 1.62 / camera.aspect)).add(camTarget.look);  /* a narrower stage stands further back: the whole city stays in frame */
    if (wide === OVERVIEW && !reducedMotion) { const drift = 1 - calm * .7; camTarget.pos.x += Math.sin(t * .09) * 2.4 * drift; camTarget.pos.y += Math.sin(t * .06) * .35 * drift; camTarget.look.x += Math.sin(t * .09) * .9 * drift; }
  }
  const k = reducedMotion ? 1 : 1 - Math.exp(-dt * (dir.free ? 6 : 2.1));
  dir.pos.lerp(camTarget.pos, k); dir.look.lerp(camTarget.look, k);
  camera.position.copy(dir.pos); camera.lookAt(dir.look);
}

function setHud() {
  const mode = dir.paused ? "Paused" : dir.free ? "Free camera" : "Following the action";
  const text = `${thought.steps ? (thought.steps[0].items[0].tour ? "Touring the brain" : "Replaying a decision") : mode} · Space pause · F free camera · G guide · W why${gpuName ? ` · ${quality} quality` : ""}`;
  if (hudEl.textContent !== text) hudEl.textContent = text;
  hudEl.title = gpuName ? `Renderer: ${gpuName}` : "";
}

/* ---------------------------------------------------------------- state into the scene */
let idleTopology = null;  /* the city stands on the plate before any run has started */
function syncCity(s) {
  if (s.topology) idleTopology = s.topology;  /* a new run resets the state, not the city */
  const topo = idleTopology;
  $("canopy").classList.toggle("no-city", !topo);
  if (!topo) return;
  const key = zoneKey(topo);
  if (key !== city.key) { city.key = key; buildCity(topo); for (const o of live.incidents.values()) groups.live.remove(o.grp); live.incidents.clear(); }
  ensureLive(s);
  const scenes = new Map([...s.incidents.values()].filter(i => i.status === "open").map(i => [i.zone, i]));
  for (const z of topo.zones) {
    const l = city.labels.get(z.id); if (!l) continue;
    const bits = [];
    if (scenes.has(z.id)) bits.push(`${INCIDENT[scenes.get(z.id).type] || scenes.get(z.id).type}`);
    if (s.held.has(z.id)) bits.push("held");
    if (s.alerts.has(z.id)) bits.push("alert sent");
    const text = bits.join(" · "); const i = l.lastChild; if (i.textContent !== text) i.textContent = text;
    l.classList.toggle("hot", scenes.has(z.id));
    l.setAttribute("data-tip", `${z.name}${s.held.has(z.id) ? " · held by a unit" : ""}${scenes.has(z.id) ? " · incident scene" : ""}`);
  }
}

const theNodeText = (id, s) => nodeText(id, s);
function syncNodes(s, from) {
  const c = s.c, a = s.attention;
  for (const n of NODES) {
    const o = nodes.get(n.id), text = theNodeText(n.id, s), lines = text || ["", "", ""];
    o.label.classList.toggle("quiet", !text);
    o.rest = text ? .34 : .08;
    const cells = o.label.querySelectorAll(".v, .sb");
    cells.forEach((cell, k) => { if (cell.textContent !== (lines[k] || "")) cell.textContent = lines[k] || ""; });
  }
  const ws = nodes.get("workspace"), lit = [...a.lit.values()].filter(x => !x.slotless).length;
  ws.seats.forEach((seat, i) => { const on = i < lit; seat.material.color.setHex(on ? COLOR.bone : COLOR.steelDim); seat.scale.setScalar(on ? 1.18 : 1); });
  const pk = nodes.get("packs"), bids = c.packs.bids || [];
  pk.orbs.forEach((orb, i) => { const b = bids[i]; orb.visible = !!b; if (b) orb.material.color.setHex((c.packs.recruited || []).includes(b.pack) ? COLOR.ember : COLOR.steelDim); });
  const mem = nodes.get("memory"), eps = Math.min(12, c.memory.episodes + ((sleepReport || {}).promoted || []).length);
  mem.rings.forEach((r, i) => { r.material.opacity = i < eps ? .85 : 0; });
  const tri = nodes.get("triage"); tri.orbs.forEach((pin, i) => { pin.visible = i < c.triage.open; });
  const fw = nodes.get("forward"); fw.extra.surprised = c.forward.n > 0 && c.forward.last ? clamp(Number(c.forward.last.z) / 12, .25, 1) : 0;
  const team = nodes.get("team"); team.extra.working = c.team.state === "working";
  nodes.get("sleep").extra.sleeping = c.sleep.state === "sleeping";
  if (from >= 0) {
    const fired = new Set();
    for (const e of events.slice(from, cursor)) {
      for (const key of pulsesFor(e)) if (!reducedMotion && emit(key)) fired.add(key.split(">")[1]);
      /* A reading rises from where it was sensed into the senses, so the city and the brain are one picture. */
      if (e.type === "brain.reading.received" && e.data && zoneOf(e.data.zone_id)) { const p = zoneOf(e.data.zone_id); ping(p, COLOR.bone); comet(V(p.x, 1.2, p.z), nodes.get("senses").group.position, COLOR.steel, 1.1, 2.4); }
      if (e.type === "brain.verdict.received" && e.data && e.data.status !== "trusted") ping(zoneOf(c.sensorZone[(e.subject || "").split("#")[0]]), COLOR.red, 3.4);
    }
    for (const n of NODES) if (c.hit[n.id] != null && c.hit[n.id] >= from && !fired.has(n.id)) bump(n.id, 3.6);
  }
}

function consume(s, from) {
  if (thought.steps) { dir.queue.length = 0; return; }  /* a replay is under way: the live events wait their turn */
  if (from < 0) { dir.queue.length = 0; return; }
  const slice = events.slice(from, cursor);
  if (cursor < from) { dir.queue.length = 0; dir.cur = null; dir.target = OVERVIEW; capEl.classList.remove("on"); return; }
  for (const e of slice) { const shot = shotFor(e, s); if (shot && !(shot.cam === null && !shot.head)) enqueue(shot, e, s); }
  if (reducedMotion && dir.queue.length) { /* no flights: cut straight to the most important shot of this step */
    const best = dir.queue.reduce((a, b) => (b.pri >= a.pri ? b : a)); dir.queue.length = 0; startShot(best); dir.until = clock.t;
  }
}

/* ---------------------------------------------------------------- the frame */
const tmp = V(0, 0, 0), tmp2 = V(0, 0, 0);
function place(el, p, dxRem = 0, dyRem = 0, side = "c") {
  const inFront = tmp.copy(p).applyMatrix4(camera.matrixWorldInverse).z < 0;  /* a point behind the camera projects to a mirrored spot */
  tmp.copy(p).project(camera);
  const behind = !inFront || tmp.z > 1, x = (tmp.x * .5 + .5) * W, y = (-tmp.y * .5 + .5) * H, r = rem();
  el.style.visibility = behind ? "hidden" : "visible";
  el.style.transform = `translate(${(x + dxRem * r).toFixed(1)}px, ${(y + dyRem * r).toFixed(1)}px) translateX(${side === "c" ? "-50%" : side === "r" ? "-100%" : "0"})`;
}

let slow = 0, frames = 0;
function draw(dt) {
  const t = clock.t;
  uTime.value = t;
  calm = lerp(calm, calmTarget, 1 - Math.exp(-dt * 1.6));
  direct(dt); moveCamera(dt); setHud();
  shell.glass.calm.value = calm; shell.glass.time.value = t; uHouse.value = (1 - calm * .7) * (post.on ? 1 : 1.4);  /* with no glow and grade the room needs more light to read the same */

  for (const o of nodes.values()) {
    o.level = Math.max(o.rest * (calm > .5 && o.id !== "sleep" && o.id !== "memory" ? .5 : 1), o.level - dt * .85);
    const lv = clamp(o.level), breathe = reducedMotion ? 0 : Math.sin(t * (o.id === "sleep" || o.id === "memory" ? .5 : 1.1) + o.group.position.x) * .04;
    const slot = shell.index.get(o.id); shell.glass.act[slot].set(o.group.position.x, o.group.position.y, o.group.position.z, Math.pow(clamp((lv - .1) / .9), 1.4)); shell.glass.age[slot] = t - o.fired;
    o.heart.material.color.copy(STEEL).lerp(BONE, lv);
    o.heart.scale.setScalar(1 + lv * .5 + breathe);
    o.halo.material.opacity = .012 + lv * .28; o.halo.material.color.copy(o.id === "team" || o.id === "gate" ? EMBER : BONE);
    if (o.id !== "gate") o.core.rotation.y += dt * (.2 + lv * .5) * (reducedMotion ? 0 : 1);
    if (!reducedMotion) o.group.position.y = o.baseY + Math.sin(t * .55 + o.group.position.x * .7) * .09;
    if (o.core.material) { o.core.material.uniforms.uLevel.value = lv; o.core.userData.lines.material.opacity = .35 + lv * .65; }
    if (o.id === "gate") { o.extra.bar.material.opacity = .5 + lv * .5; }
  }
  if (thought.part) nodes.get(thought.part).level = 1;  /* the part being explained stays lit */
  const team = nodes.get("team");
  team.orbs.forEach((orb, i) => { const a = t * (team.extra.working ? 2.4 : .5) + i * 2.094; orb.position.set(Math.cos(a) * .95, Math.sin(a * .9) * .25, Math.sin(a) * .95); orb.material.opacity = team.extra.working ? 1 : .5; });
  const fw = nodes.get("forward"); fw.extra.spark.visible = fw.extra.surprised > 0; fw.extra.spark.position.set(.6, 1.1 * fw.extra.surprised + .3, 0); fw.extra.spark.material.opacity = .5 + .5 * Math.sin(t * 7);
  const sl = nodes.get("sleep"); sl.extra.crescent.material.opacity = sl.extra.sleeping || calm > .5 ? .95 : .4; sl.extra.crescent.rotation.z = 2.3 + Math.sin(t * .4) * .05;
  nodes.get("memory").rings.forEach((r, i) => { r.rotation.z += dt * (.05 + i * .01) * (reducedMotion ? 0 : 1); });
  /* Paths: the glow of a path fades after a signal has run along it; the team's dots keep drifting. */
  for (const e of edges.values()) {
    const base = state && state.c.hit[e.from] != null && state.c.hit[e.to] != null ? .22 : .06;
    e.energy = Math.max(base, e.energy - dt * .55); e.mat.uniforms.uEnergy.value = e.shell.material.uniforms.uEnergy.value = e.energy;
  }

  for (let i = signals.length - 1; i >= 0; i--) if ((t - signals[i].t0) / signals[i].edge.dur >= 1) { const s = signals.splice(i, 1)[0]; if (s.onEnd) s.onEnd(); else if (s.edge.to) bump(s.edge.to, 3.2); }
  const g = signalPoints.geometry; let n = 0;
  for (const s of signals) {
    const k = (t - s.t0) / s.edge.dur, u = easeOut(k * .985 + .015) * .9 + k * .1;
    for (let j = 0; j <= trailLen; j++) {
      const uj = Math.max(0, u - j * (s.edge.kind === "fast" ? .018 : .026));
      setPoint(g, n++, s.edge.curve.getPointAt(uj), s.size * (1 - j / (trailLen + 1) * .85) * (j ? 1 : 1.5), (j ? .5 : 1) * (1 - j / (trailLen + 1)), s.color);
    }
  }
  for (let i = n; i < g.attributes.position.count; i++) g.attributes.aAlpha.setX(i, 0);
  g.attributes.position.needsUpdate = g.attributes.aSize.needsUpdate = g.attributes.aAlpha.needsUpdate = g.attributes.aColor.needsUpdate = true;
  g.setDrawRange(0, Math.max(n, 1));

  for (const r of rings) if (r.visible) {
    const k = (t - r.userData.t0) / r.userData.dur;
    if (k >= 1) { r.visible = false; continue; }
    r.scale.setScalar(lerp(.4, r.userData.size, easeOut(k))); r.material.opacity = (1 - k) * .85;
  }
  /* Dust drifts; it is weather, not data. */
  if (!reducedMotion) {
    const d = dustPoints.geometry.attributes.position, v = dustPoints.userData.v;
    for (let i = 0; i < MAXDUST; i++) {
      let x = d.getX(i) + v[i][0] * dt, y = d.getY(i) + v[i][1] * dt, z = d.getZ(i) + v[i][2] * dt;
      if (y > 15) y = -1; if (x > 18) x = -18; if (x < -18) x = 18;
      d.setXYZ(i, x, y, z);
    }
    d.needsUpdate = true;
  }
  /* Traffic: scenery on the roads, dim, and still when motion is reduced. */
  if (trafficPoints) {
    const cars = trafficPoints.userData.cars, tg = trafficPoints.geometry;
    for (let i = 0; i < cars.length; i++) {
      const car = cars[i], road = city.roads[car.road]; if (!road) continue;
      if (!reducedMotion) { car.u += car.v * dt * (1 - calm * .8); if (car.u > 1) car.u -= 1; if (car.u < 0) car.u += 1; }
      const len = road.a.distanceTo(road.b) || 1;
      tmp.lerpVectors(road.a, road.b, car.u); tmp.y = .08; tmp.x += -(road.b.z - road.a.z) / len * car.lane; tmp.z += (road.b.x - road.a.x) / len * car.lane;
      setPoint(tg, i, tmp, .16, .9 * (1 - calm * .6), car.warm ? WINDOW : BONE, 0);
    }
    for (const a of ["position", "aSize", "aAlpha", "aColor"]) tg.attributes[a].needsUpdate = true;
  }

  /* The city's live marks. */
  for (const [id, o] of live.incidents) {
    const age = t - o.born; o.beam.material.uniforms.uOpacity.value = (.5 + .2 * Math.sin(t * 3)) * easeOut(age / .6); o.beam.scale.set(1 + Math.sin(t * 2) * .12, easeOut(age / .5), 1 + Math.sin(t * 2) * .12);
    o.pool.material.opacity = (.34 + .1 * Math.sin(t * 3)) * easeOut(age / .5);
    o.rim.forEach((r, i) => { const k = ((t * .45 + i * .5) % 1); r.scale.setScalar(.8 + k * 4.2); r.material.opacity = (1 - k) * .95; });
  }
  for (const f of live.fences.values()) { f.material.opacity = .6 + .2 * Math.sin(t * 2); f.userData.pool.material.opacity = .18; }
  for (const r of plan.pings) if (r.visible) {
    const k = (t - r.userData.t0) / 1.1;
    if (k >= 1) { r.visible = false; continue; }
    r.scale.setScalar(.4 + easeOut(k) * r.userData.size); r.material.opacity = (1 - k) * .9;
  }
  for (const [id, o] of live.units) {
    const zone = city.zones.get(o.zone); if (!zone) continue;
    const target = zone.clone().add(V(1.3 + o.n * .8, ROOFS + Math.sin(t * 1.6 + o.n) * .06, -.4 - o.n * .5)), k = reducedMotion ? 1 : easeOut((t - o.born) / 1.5);
    o.body.position.lerpVectors(o.from, target, k);
    place(o.lab, o.body.position.clone().add(V(0, .75, 0)), 0, -.4, "c");
  }
  for (const [id, o] of live.beacons) {
    const zone = city.zones.get(id); if (!zone) continue;
    const target = zone.clone().add(V(0, ROOFS + .6, 0)), k = reducedMotion ? 1 : easeOut((t - o.born) / 1.5);
    o.body.position.lerpVectors(o.from, target, k);
    o.rim.forEach((r, i) => { const q = ((t * .38 + i / 3) % 1); r.scale.setScalar(.8 + q * 5); r.material.opacity = (1 - q) * .75; });
  }
  for (const o of live.suspects.values()) { o.m.rotation.y += dt * 1.2; o.m.position.y = ROOFS + Math.sin(t * 2 + o.m.position.x) * .08; place(o.lab, o.m.position.clone(), -.9, -.55, "r"); }
  if (city.focus) {
    const f = city.focus, want = dir.focus && !dir.free ? 1 : 0;
    if (dir.focus) f.position.x = lerp(f.position.x, dir.focus.x, reducedMotion ? 1 : 1 - Math.exp(-dt * 6)), f.position.z = lerp(f.position.z, dir.focus.z, reducedMotion ? 1 : 1 - Math.exp(-dt * 6));
    f.material.opacity = lerp(f.material.opacity, want * (.6 + .2 * Math.sin(t * 3)), 1 - Math.exp(-dt * 5));
  }
  drawStrings();

  /* Labels follow their points. */
  for (const [id, l] of city.labels) { const z = city.zones.get(id); if (z) place(l, tmp2.copy(z).setZ(z.z + HEX * .9), 0, .35, "c"); }
  for (const n of NODES) { const o = nodes.get(n.id), [dx, dy, side] = LAB[n.id]; place(o.label, o.group.position, dx, dy, side); }
  placeChips();
  present();

  /* A high tier that cannot hold its frame rate gives way to the light tier. */
  if (quality === "high" && dt > 0 && running) {
    frames++; if (dt > 1 / 24) slow++;
    if (frames >= 120) { if (slow / frames > .5) setQuality("light"); frames = slow = 0; }
  }
}

/* ---------------------------------------------------------------- the frame goes out */
/* High tier only: the scene in linear light with its highlights kept, a soft glow from what is brighter than white (halved a few times
   and grown back, which costs little), then a filmic grade. Written by hand because the vendored three.js has no addons. A glow once
   drew half this canvas black on one driver: not-a-number pixels spread as they blur, so the first step refuses them, and a frame that
   still comes out black on the left turns the pass off. */
const post = { can: false, on: false, target: null, down: [], up: [], scene: null, camera: null, quad: null, mats: null, frame: 0 };
function fullScreen(fragmentShader, uniforms) {
  return new THREE.ShaderMaterial({ depthTest: false, depthWrite: false, uniforms, fragmentShader, vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }` });
}
function buildPost() {
  post.on = post.can && quality === "high" && !post.failed; post.frame = 0;
  if (!post.on || post.scene) { if (post.on) sizePost(); return; }
  post.scene = new THREE.Scene(); post.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  post.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2)); post.quad.frustumCulled = false; post.scene.add(post.quad);
  post.mats = {
    down: fullScreen(`varying vec2 vUv; uniform sampler2D tex; uniform vec2 px; uniform float first;
      vec3 pick(vec2 at) { vec3 c = texture2D(tex, at).rgb; if (any(notEqual(c, c))) return vec3(0.0); return min(c, vec3(14.0)); }
      void main() { vec3 c = pick(vUv) * 4.0 + pick(vUv + px * vec2(-1.0, -1.0)) + pick(vUv + px * vec2(1.0, -1.0)) + pick(vUv + px * vec2(-1.0, 1.0)) + pick(vUv + px); c /= 8.0;
        if (first > 0.5) c *= smoothstep(0.7, 1.5, max(c.r, max(c.g, c.b))); gl_FragColor = vec4(c, 1.0); }`, { tex: { value: null }, px: { value: new THREE.Vector2() }, first: { value: 0 } }),
    up: fullScreen(`varying vec2 vUv; uniform sampler2D tex; uniform sampler2D same; uniform vec2 px;
      void main() { vec3 c = vec3(0.0); vec2 h = px * 0.5;
        c += texture2D(tex, vUv + vec2(-h.x * 2.0, 0.0)).rgb + texture2D(tex, vUv + vec2(h.x * 2.0, 0.0)).rgb + texture2D(tex, vUv + vec2(0.0, -h.y * 2.0)).rgb + texture2D(tex, vUv + vec2(0.0, h.y * 2.0)).rgb;
        c += 2.0 * (texture2D(tex, vUv + h).rgb + texture2D(tex, vUv - h).rgb + texture2D(tex, vUv + vec2(h.x, -h.y)).rgb + texture2D(tex, vUv + vec2(-h.x, h.y)).rgb);
        gl_FragColor = vec4(c / 12.0 + texture2D(same, vUv).rgb * 0.5, 1.0); }`, { tex: { value: null }, same: { value: null }, px: { value: new THREE.Vector2() } }),
    out: fullScreen(`varying vec2 vUv; uniform sampler2D tex; uniform sampler2D glow; uniform float seed;
      void main() { vec3 c = texture2D(tex, vUv).rgb; if (any(notEqual(c, c))) c = vec3(0.0); c = min(c, vec3(14.0)) + texture2D(glow, vUv).rgb * 0.42;
        c *= 1.12; c = (c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14);
        c += (fract(sin(dot(gl_FragCoord.xy + seed, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) / 255.0;
        gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0); gl_FragColor = linearToOutputTexel(gl_FragColor); }`, { tex: { value: null }, glow: { value: null }, seed: { value: 0 } }),
  };
  sizePost();
}
function sizePost() {
  if (!post.on || !W) return;
  const pr = renderer.getPixelRatio(), w = Math.round(W * pr), h = Math.round(H * pr), type = THREE.HalfFloatType;
  if (post.target) { post.target.dispose(); for (const t of [...post.down, ...post.up]) t.dispose(); }
  post.target = new THREE.WebGLRenderTarget(w, h, { type, samples: 4 });
  post.down = []; post.up = [];
  for (let i = 1, dw = w, dh = h; i <= 5; i++) {
    dw = Math.max(2, dw >> 1); dh = Math.max(2, dh >> 1);
    post.down.push(new THREE.WebGLRenderTarget(dw, dh, { type, depthBuffer: false }));
    post.up.push(new THREE.WebGLRenderTarget(dw, dh, { type, depthBuffer: false }));
  }
}
function pass(material, target) { post.quad.material = material; renderer.setRenderTarget(target); renderer.render(post.scene, post.camera); }
function present() {
  renderer.setRenderTarget(plan.target); renderer.setClearColor(0x000000, 1); renderer.clear(); renderer.render(plan.scene, plan.camera); renderer.setRenderTarget(null);
  if (!post.on || !post.target) { renderer.render(scene, camera); return; }
  renderer.setRenderTarget(post.target); renderer.render(scene, camera);
  const { down, up, out } = post.mats, n = post.down.length;
  let source = post.target.texture;
  for (let i = 0; i < n; i++) {
    down.uniforms.tex.value = source; down.uniforms.first.value = i === 0 ? 1 : 0; down.uniforms.px.value.set(1 / post.down[i].width, 1 / post.down[i].height);
    pass(down, post.down[i]); source = post.down[i].texture;
  }
  for (let i = n - 2; i >= 0; i--) {
    up.uniforms.tex.value = source; up.uniforms.same.value = post.down[i].texture; up.uniforms.px.value.set(1 / post.up[i].width, 1 / post.up[i].height);
    pass(up, post.up[i]); source = post.up[i].texture;
  }
  out.uniforms.tex.value = post.target.texture; out.uniforms.glow.value = source; out.uniforms.seed.value = reducedMotion ? 0 : clock.t % 7;
  pass(out, null);
  if (++post.frame === 12) {
    const gl = renderer.getContext(), px = new Uint8Array(4), bw = gl.drawingBufferWidth, bh = gl.drawingBufferHeight; let lit = 0;
    for (const [u, v] of [[.08, .2], [.08, .8], [.25, .5], [.4, .15], [.4, .85]]) { gl.readPixels(Math.floor(bw * u), Math.floor(bh * v), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); lit += px[0] + px[1] + px[2]; }
    if (!lit) { post.on = false; post.failed = true; console.warn("Canopy: the glow pass drew black on this driver; it is off."); }
  }
}

let chips = new Map();
function placeChips() {
  if (!state) return;
  const make = (key, text, edgeKey, at, dx, dy) => {
    let c = chips.get(key);
    if (!text) { if (c) { c.remove(); chips.delete(key); } return; }
    if (!c) { c = document.createElement("div"); c.className = "chip3 k-" + key; labelLayer.append(c); chips.set(key, c); }
    if (c.textContent !== text) c.textContent = text;
    place(c, edges.get(edgeKey).curve.getPointAt(at), dx, dy, "c");
  };
  make("reflex", state.c.reflex.ms != null ? `reflex ${sec(state.c.reflex.ms)}` : "", "reflex>gate", .9, -4.4, 1.1);
  make("team", state.c.team.ms != null ? `team ${sec(state.c.team.ms)}` : "", "team>gate", .9, 4.2, 1.3);
}

function setQuality(q) {
  if (q === quality) return;
  quality = q; renderer.setPixelRatio(Math.min(devicePixelRatio || 1, q === "high" ? 2 : 1.25));
  plan.target.setSize(q === "high" ? 1024 : 640, q === "high" ? 640 : 400); buildPost();
  city.key = ""; resize(); if (state) syncCity(state);
}

function loop(now) {
  if (!running) return;
  requestAnimationFrame(loop);
  if (host.hidden) { clock.last = now; return; }
  const dt = Math.min(.1, (now - clock.last) / 1000 || 0); clock.last = now; clock.t += dt;
  calmTarget = host.classList.contains("asleep") && !thought.steps ? 1 : 0;
  draw(dt);
}

/* Free camera: drag to orbit, wheel to zoom. Following is the default and the presenter's hands stay off the mouse. */
function bindFree() {
  let drag = null;
  stage.addEventListener("pointerdown", ev => { if (!dir.free) return; drag = { x: ev.clientX, y: ev.clientY }; stage.setPointerCapture(ev.pointerId); });
  stage.addEventListener("pointermove", ev => {
    if (!drag || !dir.free) return;
    dir.orbit.yaw -= (ev.clientX - drag.x) * .005; dir.orbit.pitch = clamp(dir.orbit.pitch + (ev.clientY - drag.y) * .004, .12, 1.3); drag = { x: ev.clientX, y: ev.clientY };
    if (!running) draw(.016);
  });
  stage.addEventListener("pointerup", () => { drag = null; });
  stage.addEventListener("wheel", ev => { if (!dir.free) return; ev.preventDefault(); dir.orbit.dist = clamp(dir.orbit.dist * (1 + Math.sign(ev.deltaY) * .08), 12, 60); if (!running) draw(.016); }, { passive: false });
}

/* ---------------------------------------------------------------- the page's side */
try {
  build(); bindFree();
  ok = true;
} catch (error) {
  console.warn("3D canopy unavailable, keeping the flat canopy:", error.message);
  stage.remove();
}

if (ok) {
  const api = {
    ok: true,
    update(s, from) {
      state = s; syncNodes(s, from); syncCity(s); consume(s, from);
      if (reducedMotion) { clock.t += .016; draw(.016); }
    },
    start() { if (running || reducedMotion) return; running = true; clock.last = performance.now(); requestAnimationFrame(loop); },
    stop() { running = false; },
    replayThought(explanation) { const ok = startThought(explanation); if (ok && reducedMotion) { thoughtTick(); draw(.016); thought.steps = null; window.dispatchEvent(new Event("thoughtend")); } return ok; },
    stopThought() { if (thought.steps) endThought(); },
    nextThought() { if (thought.steps) thought.at = 0; },
    get replaying() { return !!thought.steps; },
    togglePause() { dir.paused = !dir.paused; if (!running) draw(0); return dir.paused; },
    toggleFree() { dir.free = !dir.free; if (dir.free) { const o = dir.orbit, c = OVERVIEW.look; o.dist = dir.pos.distanceTo(c); o.yaw = Math.atan2(dir.pos.x - c.x, dir.pos.z - c.z); o.pitch = clamp(Math.asin((dir.pos.y - c.y) / Math.max(o.dist, .1)), .12, 1.3); } if (!running) draw(0); return dir.free; },
    resize,
    get quality() { return quality; },
    get renderer() { return gpuName; },
    setQuality,
    debug: { renderer, scene, THREE, dir, nodes, post },
  };
  window.canopy3d = api;
  fetch("/api/topology").then(r => (r.ok ? r.json() : null)).then(t => { if (t && t.zones && t.zones.length) { idleTopology = t; if (state) syncCity(state); } }).catch(() => {});
  if (typeof view !== "undefined" && view === "canopy") { api.start(); render(); }
}
