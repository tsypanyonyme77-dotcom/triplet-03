/* The glass of the canopy's brain: a see-through cortex with its folds, a cerebellum and a brain stem, drawn in code so no model
   file is fetched. The front of the brain is +x (the flow from the senses to the packs reads left to right) and the camera looks
   from +z, so the near hemisphere is the one the audience sees.

   One shader dresses all three pieces, far wall first and near wall last, so the folds read as relief and not as haze. It also takes
   the eleven regions' positions and levels as uniforms: a region that fires lights the gyri around it and sends a wave across the
   cortex, so the glass shows where the Brain is working even when the region itself is deep inside. The shapes of the regions are
   drawn by canopy3d.js; this module knows only where the glass is. */

export const ANATOMY = { centre: [0, 9.9, 0], a: 11.2, top: 6.8, bottom: 4.8, depth: 5.2 };
export const MAX_REGIONS = 11;

const smooth = (lo, hi, x) => { const t = Math.max(0, Math.min(1, (x - lo) / (hi - lo))); return t * t * (3 - 2 * t); };

function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

/* Value noise in three dimensions: smooth, cheap, and good enough for the grooves of a cortex. */
function lattice(x, y, z) { let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function noise(x, y, z) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z), u = smooth(0, 1, x - xi), v = smooth(0, 1, y - yi), w = smooth(0, 1, z - zi);
  const c = (dx, dy, dz) => lattice(xi + dx, yi + dy, zi + dz), mix = (a, b, k) => a + (b - a) * k;
  return mix(mix(mix(c(0, 0, 0), c(1, 0, 0), u), mix(c(0, 1, 0), c(1, 1, 0), u), v), mix(mix(c(0, 0, 1), c(1, 0, 1), u), mix(c(0, 1, 1), c(1, 1, 1), u), v), w);
}
/* A sulcus is where the noise crosses one half: a thin line on the surface, so the gyri between them stay broad. */
const sulcus = (x, y, z, freq, width) => 1 - smooth(0, width, Math.abs(2 * noise(x * freq, y * freq, z * freq) - 1));

function cortexFold(x, y, z) { return Math.max(sulcus(x, y, z, .46, .22), .8 * sulcus(x + 9.1, y - 4.3, z + 2.7, .95, .28)); }

/* The two grooves a side view of a brain is recognised by: the lateral fissure above the temporal lobe, and the central sulcus that
   falls to meet it. Both only on the outer surface, in coordinates around the centre of the cortex. */
const lateralY = x => -.55 - .26 * x;
function fissure(x, y, z) {
  const outer = smooth(.8, 2.2, Math.abs(z));
  const lateral = Math.exp(-(((y - lateralY(x)) / .36) ** 2)) * smooth(-6, -4, x) * (1 - smooth(5, 6.5, x)) * outer;
  const central = Math.exp(-(((x - (1.2 - .35 * y)) / .3) ** 2)) * smooth(lateralY(x), lateralY(x) + .8, y) * outer;
  return Math.max(lateral, .72 * central);
}

/* From a point on the unit sphere to the cortex: a narrower frontal lobe with a flatter underside, an occipital pole that droops, a
   temporal lobe underneath, and a fissure down the middle. */
function cortexPoint(ux, uy, uz) {
  const A = ANATOMY, front = smooth(0, 1, ux), back = smooth(0, 1, -ux);
  const x = ux * A.a, z = uz * A.depth * (1 - .3 * front - .08 * back);
  let y = uy * (uy >= 0 ? A.top : A.bottom * (1 - .38 * front));
  y -= 1.1 * back * back;
  const temporal = Math.exp(-(((x - 1.9) / 4.6) ** 2)) * Math.exp(-(((y + 3.2) / 1.9) ** 2)) * smooth(.8, 3.2, Math.abs(z));
  y -= 1.15 * temporal;
  const midline = Math.exp(-((z / .5) ** 2));
  if (y > -1) y -= 1.15 * midline * smooth(-.15, .25, uy);
  const nx = x / (A.a * A.a), ny = y / ((y >= 0 ? A.top : A.bottom) ** 2), nz = z / (A.depth * A.depth), len = Math.hypot(nx, ny, nz) || 1;
  const gyri = cortexFold(x, y, z), cut = fissure(x, y, z), fold = Math.max(gyri, cut), push = -.34 * gyri - .62 * cut + .08 * (1 - fold);
  return { p: [x + nx / len * push, y + ny / len * push, z + nz / len * push], fold: Math.max(fold, midline * smooth(0, .4, uy)) };
}

/* The cerebellum tucks under the occipital pole. Its leaves fan out from the middle, and a shallow groove divides it in two. */
const CEREBELLUM = { at: [-6.7, 5.7, 0], r: [3.7, 2.35, 4.2] };
function cerebellumPoint(ux, uy, uz) {
  const [rx, ry, rz] = CEREBELLUM.r, x = ux * rx, y = uy * (uy >= 0 ? ry * .78 : ry), z = uz * rz;
  const stripe = Math.abs(Math.sin(Math.atan2(y, x + .6) * 15 + .9 * noise(x * .5, y * .5, z * .5))), leaf = 1 - smooth(0, .34, stripe);
  const vermis = Math.exp(-((z / .55) ** 2)), fold = Math.max(leaf, .8 * vermis), len = Math.hypot(ux, uy, uz) || 1, push = -.2 * leaf - .34 * vermis;
  return { p: [x + ux / len * push, y + uy / len * push, z + uz / len * push], fold };
}

/* Normals of a displaced sphere split along its seam and at its poles; adding up the normals of vertices at one place closes them. */
function weld(geometry) {
  geometry.computeVertexNormals();
  const pos = geometry.attributes.position, nor = geometry.attributes.normal, sums = new Map();
  const key = i => `${Math.round(pos.getX(i) * 400)},${Math.round(pos.getY(i) * 400)},${Math.round(pos.getZ(i) * 400)}`;
  for (let i = 0; i < pos.count; i++) { const k = key(i), s = sums.get(k) || [0, 0, 0]; s[0] += nor.getX(i); s[1] += nor.getY(i); s[2] += nor.getZ(i); sums.set(k, s); }
  for (let i = 0; i < pos.count; i++) { const s = sums.get(key(i)), l = Math.hypot(...s) || 1; nor.setXYZ(i, s[0] / l, s[1] / l, s[2] / l); }
}

function shapedSphere(THREE, segments, at, point) {
  const g = new THREE.SphereGeometry(1, segments[0], segments[1]), pos = g.attributes.position, fold = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    const { p, fold: f } = point(pos.getX(i), pos.getY(i), pos.getZ(i));
    pos.setXYZ(i, p[0] + at[0], p[1] + at[1], p[2] + at[2]); fold[i] = f;
  }
  g.setAttribute("aFold", new THREE.BufferAttribute(fold, 1)); weld(g); return g;
}

const VERTEX = `attribute float aFold; varying vec3 vN; varying vec3 vW; varying float vFold;
  void main() { vFold = aFold; vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); gl_Position = projectionMatrix * viewMatrix * w; }`;
/* Glass, written premultiplied: light it gives off, and how much of what is behind it it hides. Crests catch a key light and the edge
   catches the rim; grooves give off little and hide more, so they read dark. A region's light follows the gyri near it, and a firing
   sends one ring across the surface. */
const FRAGMENT = `uniform vec4 uAct[${MAX_REGIONS}]; uniform vec3 uCol[${MAX_REGIONS}]; uniform float uAge[${MAX_REGIONS}]; uniform float uCalm; uniform float uTime; uniform float uStrength; uniform float uBack;
  varying vec3 vN; varying vec3 vW; varying float vFold;
  void main() {
    vec3 n = normalize(vN) * (uBack > 0.5 ? -1.0 : 1.0), v = normalize(cameraPosition - vW);
    float ndv = clamp(dot(n, v), 0.0, 1.0), rim = pow(1.0 - ndv, 2.6), ridge = 1.0 - vFold;
    float key = max(dot(n, normalize(vec3(-0.35, 0.8, 0.5))), 0.0), fill = max(dot(n, normalize(vec3(0.7, -0.2, 0.6))), 0.0);
    vec3 pearl = mix(vec3(0.05, 0.09, 0.15), vec3(0.50, 0.60, 0.72), ridge);
    vec3 light = pearl * (0.02 + 0.13 * key + 0.03 * fill) + vec3(0.55, 0.74, 1.0) * rim * (0.2 + 0.8 * ridge) * 0.34;
    light *= 1.0 + 0.1 * sin(vW.x * 0.55 - uTime * 0.7) * (1.0 - uCalm);
    float hide = 0.09 + 0.12 * key * ridge + 0.20 * vFold + 0.42 * rim;
    vec3 glow = vec3(0.0); float lit = 0.0;
    for (int i = 0; i < ${MAX_REGIONS}; i++) {
      float d = distance(vW, uAct[i].xyz), age = uAge[i];
      float ring = age < 2.6 ? exp(-pow((d - age * 7.5) / 1.3, 2.0)) * exp(-age * 1.5) : 0.0;
      float k = uAct[i].w * exp(-d * d / 11.0) + 0.5 * ring;
      glow += uCol[i] * k; lit += k;
    }
    float dim = (1.0 - 0.45 * uCalm) * uStrength;
    light = (light + glow * (0.05 + 0.5 * ridge)) * dim;
    gl_FragColor = vec4(min(light, vec3(1.6)), clamp((hide + lit * 0.16) * dim, 0.0, 0.85));
    gl_FragColor = linearToOutputTexel(gl_FragColor);
  }`;

/* Neurons are specks that twinkle inside the glass; tracts are faint fibres between its far ends. Both are texture, not data. */
function inside(r) { for (;;) { const x = (r() * 2 - 1), y = (r() * 2 - 1), z = (r() * 2 - 1); if (x * x + y * y + z * z < .8) return [x * ANATOMY.a * .92, y * (y > 0 ? ANATOMY.top : ANATOMY.bottom) * .9, z * ANATOMY.depth * .85]; } }

export function buildBrainShell(THREE, quality, kit) {
  const high = quality === "high", at = ANATOMY.centre;
  const uniforms = {
    uAct: { value: Array.from({ length: MAX_REGIONS }, () => new THREE.Vector4(0, 0, 0, 0)) },
    uCol: { value: Array.from({ length: MAX_REGIONS }, () => new THREE.Vector3(1, 1, 1)) },
    uAge: { value: new Array(MAX_REGIONS).fill(99) },
    uCalm: { value: 0 }, uTime: { value: 0 },
  };
  /* The far wall is drawn before the regions and the near wall after them, so the regions sit inside the glass. */
  const glass = (strength, back) => new THREE.ShaderMaterial({ uniforms: { ...uniforms, uStrength: { value: strength }, uBack: { value: back ? 1 : 0 } }, vertexShader: VERTEX, fragmentShader: FRAGMENT, transparent: true, depthWrite: false, side: back ? THREE.BackSide : THREE.FrontSide, premultipliedAlpha: true });
  const group = new THREE.Group();
  const walls = (geometry, strength, place) => {
    for (const back of [true, false]) {
      const m = new THREE.Mesh(geometry, glass(back ? strength * .4 : strength, back));
      m.renderOrder = back ? 1 : 4; m.frustumCulled = false; if (place) place(m); group.add(m);
    }
  };
  walls(shapedSphere(THREE, high ? [384, 240] : [200, 124], at, cortexPoint), 1);
  walls(shapedSphere(THREE, high ? [200, 120] : [110, 64], CEREBELLUM.at, cerebellumPoint), .85);
  /* The stem: medulla at the foot, the pons swelling under the cortex, ringed so it does not read as a pipe. */
  const profile = [[.48, -2], [.56, -1.2], [.66, -.5], [1.02, .35], [1.14, .95], [.98, 1.5], [.82, 2]].map(([r, y]) => new THREE.Vector2(r, y));
  const stemGeometry = new THREE.LatheGeometry(new THREE.SplineCurve(profile).getPoints(28), 32), fold = new Float32Array(stemGeometry.attributes.position.count);
  for (let i = 0; i < fold.length; i++) fold[i] = .5 * Math.max(0, Math.sin(stemGeometry.attributes.position.getY(i) * 7)) ** 2;
  stemGeometry.setAttribute("aFold", new THREE.BufferAttribute(fold, 1));
  walls(stemGeometry, .7, m => { m.position.set(.2, 4.7, 0); m.rotation.z = .1; });

  const r = rng(2026), count = high ? 460 : 240, neurons = kit.pointsGeometry(count);
  for (let i = 0; i < count; i++) {
    const [x, y, z] = inside(r);
    kit.setPoint(neurons, i, new THREE.Vector3(x + at[0], y + at[1], z + at[2]), .05 + r() * .06, .12 + r() * .3, kit.col(r() > .75 ? 0xf2b552 : 0x6d8cab), r());
  }
  const points = new THREE.Points(neurons, kit.glowMaterial(1)); points.frustumCulled = false; points.renderOrder = 2; group.add(points);

  const tracts = [], n = high ? 44 : 24;
  for (let i = 0; i < n; i++) {
    let a = inside(r), b = inside(r);
    while (Math.abs(a[0] - b[0]) < 7) b = inside(r);
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 1.6 + r() * 1.4, (a[2] + b[2]) / 2 + (r() - .5) * 2];
    const curve = new THREE.CatmullRomCurve3([a, mid, b].map(p => new THREE.Vector3(p[0] + at[0], p[1] + at[1], p[2] + at[2]))), pts = curve.getPoints(14);
    for (let k = 1; k < pts.length; k++) tracts.push(pts[k - 1].x, pts[k - 1].y, pts[k - 1].z, pts[k].x, pts[k].y, pts[k].z);
  }
  const tg = new THREE.BufferGeometry(); tg.setAttribute("position", new THREE.Float32BufferAttribute(tracts, 3));
  const fibres = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({ color: 0x6d8cab, transparent: true, opacity: .1, blending: THREE.AdditiveBlending, depthWrite: false }));
  fibres.frustumCulled = false; fibres.renderOrder = 2; group.add(fibres);

  return { group, act: uniforms.uAct.value, tint: uniforms.uCol.value, age: uniforms.uAge.value, calm: uniforms.uCalm, time: uniforms.uTime };
}
