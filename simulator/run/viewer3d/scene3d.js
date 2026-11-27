// HydroPin – 3D view of the prototype board (viewer tab "3D board").
// Built from the twin's own geometry (BD.pos, BD.xy, BD.links: network/prototype.py) and
// coloured / animated with the twin's states (BD.states: steady/board.py), so the 3D and the
// simulation cannot drift apart. Units: centimetres. X right, Y up, Z towards the viewer.
// Build: npx esbuild scene3d.js --bundle --minify --format=iife --global-name=HP3D --outfile=hp3d.bundle.js
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

// ── placement on the table (assumptions, listed in the side panel) ──────────────────────────
const TABLE = { w: 140, d: 75, h: 75, top: 3 };
const BOARD = { x0: -20, z0: 33, w: 60, d: 40, t: 1.8 };          // board (0,0) corner at the front-left
const R_PE = 0.8;                                                   // 16 mm pipe
const YP = TABLE.h + BOARD.t + R_PE + 0.3;                          // pipe axis height (on clips)
const BUCKET = { x: 15, z: 54, rTop: 15, rBot: 13, h: 35, water: 28 };
const PUMP = { x: -16, z: 50 };
const BOX = { x: 56, z: 20, w: 14, d: 10, h: 4.5 };

const bp = (bx, by, y = YP) => new THREE.Vector3(BOARD.x0 + bx, y, BOARD.z0 - by);

// theme (optional, used by the dashboard): { bg, floor } colours of the room
export function init(BD, host, ui, theme = {}) {
  const W = () => host.clientWidth, H = () => host.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(W(), H());
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const BG = theme.bg || '#f4f3ef';
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 420, 900);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.22;
  const camera = new THREE.PerspectiveCamera(38, W() / H(), 1, 3000);
  const HOME = { pos: new THREE.Vector3(95, 165, 175), target: new THREE.Vector3(12, 62, 20) };
  camera.position.copy(HOME.pos);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(HOME.target);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 25;
  controls.maxDistance = 520;
  controls.update();

  // lights
  scene.add(new THREE.HemisphereLight('#ffffff', '#d9d4c7', 0.85));
  const sun = new THREE.DirectionalLight('#ffffff', 1.55);
  sun.position.set(-120, 260, 160);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -160, right: 160, top: 160, bottom: -160, near: 50, far: 600 });
  sun.shadow.bias = -0.0004;
  scene.add(sun);

  // ── materials ──
  const M = (o) => new THREE.MeshStandardMaterial(o);
  const mat = {
    floor: M({ color: theme.floor || '#e9e6de', roughness: 0.95 }),
    wood: M({ color: '#c8a77a', roughness: 0.8 }),
    tableTop: M({ color: '#f1efe9', roughness: 0.7 }),
    leg: M({ color: '#9a9890', roughness: 0.5, metalness: 0.4 }),
    ply: M({ color: '#e2c99d', roughness: 0.85 }),
    black: M({ color: '#1f2022', roughness: 0.55 }),
    fitting: M({ color: '#2a2b2e', roughness: 0.5 }),
    steel: M({ color: '#c9ced3', roughness: 0.25, metalness: 0.9 }),
    brass: M({ color: '#c99a2e', roughness: 0.3, metalness: 0.85 }),
    red: M({ color: '#d03b3b', roughness: 0.45 }),
    blue: M({ color: '#2a78d6', roughness: 0.45 }),
    valveBody: M({ color: '#3a4a5c', roughness: 0.45 }),
    hose: M({ color: '#d6ecf5', roughness: 0.15, transparent: true, opacity: 0.55 }),
    bucket: M({ color: '#f6f6f2', roughness: 0.4, transparent: true, opacity: 0.72, side: THREE.DoubleSide }),
    water: M({ color: '#4aa3df', roughness: 0.1, transparent: true, opacity: 0.6 }),
    pcbGreen: M({ color: '#1f6f43', roughness: 0.6 }),
    pcbBlue: M({ color: '#1d4fa8', roughness: 0.6 }),
    pcbBlack: M({ color: '#202124', roughness: 0.6 }),
    breadboard: M({ color: '#f7f7f2', roughness: 0.8 }),
    boxGrey: M({ color: '#d8d9dc', roughness: 0.6, transparent: true, opacity: 0.55 }),
    cable: M({ color: '#3b3b3b', roughness: 0.7 }),
    cableRed: M({ color: '#b4302b', roughness: 0.7 }),
    laptop: M({ color: '#9fa3a9', roughness: 0.35, metalness: 0.6 }),
    motor: M({ color: '#b8bcc2', roughness: 0.3, metalness: 0.9 }),
  };
  const add = (mesh, shadow = true) => { mesh.castShadow = shadow; mesh.receiveShadow = true; scene.add(mesh); return mesh; };
  const box = (w, h, d, m, x, y, z) => { const o = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); o.position.set(x, y, z); return add(o); };
  function cylBetween(a, b, r, m, seg = 20, hseg = 1) {
    const dir = new THREE.Vector3().subVectors(b, a), len = dir.length();
    const g = new THREE.CylinderGeometry(r, r, len, seg, hseg);
    const o = new THREE.Mesh(g, m);
    o.position.copy(a).addScaledVector(dir, 0.5);
    o.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    add(o);
    o.userData.len = len;
    return o;
  }
  const tube = (pts, r, m, n = 64) => add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n, r, 12, false), m));

  // ── room, table, board ──
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), mat.floor);
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  box(TABLE.w, TABLE.top, TABLE.d, mat.tableTop, 0, TABLE.h - TABLE.top / 2, 0);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(4, TABLE.h - TABLE.top, 4, mat.leg, sx * (TABLE.w / 2 - 6), (TABLE.h - TABLE.top) / 2, sz * (TABLE.d / 2 - 6));
  box(BOARD.w, BOARD.t, BOARD.d, mat.ply, BOARD.x0 + BOARD.w / 2, TABLE.h + BOARD.t / 2, BOARD.z0 - BOARD.d / 2);

  // ── pipes on the board (one mesh per twin link) ──
  const stripeTex = (() => {
    const c = document.createElement('canvas'); c.width = 8; c.height = 64;
    const g = c.getContext('2d'); g.fillStyle = '#ffffff'; g.fillRect(0, 0, 8, 64);
    g.fillStyle = '#9aa0a8'; g.fillRect(0, 0, 8, 22);
    const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const P = (id) => bp(BD.pos[id][0], BD.pos[id][1]);
  const pipes = BD.links.map(([a, b], k) => {
    const tex = stripeTex.clone(); tex.needsUpdate = true;
    const m = M({ color: '#ffffff', roughness: 0.45, map: tex, vertexColors: true });
    const o = cylBetween(P(a), P(b), R_PE, m, 20, 10);
    const g = o.geometry, pos = g.attributes.position, L = o.userData.len;
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pos.count * 3), 3));
    o.userData.frac = Float32Array.from({ length: pos.count }, (_, i) => (pos.getY(i) + L / 2) / L);
    tex.repeat.set(1, Math.max(1, o.userData.len / 3));
    const id = BD.link_ids[k];
    const isSS = id.startsWith('SS_'), isValve = id.startsWith('VALVE_');
    if (isSS) { o.material = M({ color: '#ffffff', roughness: 0.25, metalness: 0.85, vertexColors: true }); o.scale.set(0.85, 1, 0.85); }
    if (isValve) o.visible = false;              // drawn as a valve body below
    return { mesh: o, tex, k, ss: isSS, a, b, id };
  });

  // fittings: tees, elbows, reducer
  const xy = (id) => bp(BD.xy[id][0], BD.xy[id][1]);
  for (const id of ['T0', 'TL1', 'TL2', 'TL3', 'T1']) { const p = xy(id); box(3.2, 2.1, 2.1, mat.fitting, p.x, p.y, p.z); }
  for (const id of ['E1', 'E2', 'E3']) { const p = xy(id); const s = add(new THREE.Mesh(new THREE.SphereGeometry(1.15, 20, 14), mat.fitting)); s.position.copy(p); }
  const pIn = xy('IN');
  { const c = add(new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.95, 2.2, 18), mat.fitting)); c.position.set(pIn.x - 1.0, pIn.y, pIn.z); c.rotation.z = Math.PI / 2; }

  // flow sensor F0 (brass G1/2 body, hex ends, Hall cap)
  const fa = bp(12.3, 17), fb = bp(18.6, 17);
  cylBetween(fa, fb, 1.45, mat.brass);
  cylBetween(fa.clone().add(new THREE.Vector3(-0.6, 0, 0)), fa.clone().add(new THREE.Vector3(0.6, 0, 0)), 1.75, mat.brass, 6);
  cylBetween(fb.clone().add(new THREE.Vector3(-0.6, 0, 0)), fb.clone().add(new THREE.Vector3(0.6, 0, 0)), 1.75, mat.brass, 6);
  const fcap = box(2.4, 1.4, 2.0, mat.black, (fa.x + fb.x) / 2, YP + 1.9, fa.z);

  // valves R1 R2 V1 V2 (body + lever that turns with the angle)
  const levers = {};
  for (const v of ['R1', 'R2', 'V1', 'V2']) {
    const p = xy(v);
    cylBetween(p.clone().add(new THREE.Vector3(-2.6, 0, 0)), p.clone().add(new THREE.Vector3(2.6, 0, 0)), 1.25, mat.valveBody);
    const stem = add(new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 1.6, 10), mat.steel)); stem.position.set(p.x, p.y + 1.8, p.z);
    const piv = new THREE.Group(); piv.position.set(p.x, p.y + 2.6, p.z); scene.add(piv);
    const lev = new THREE.Mesh(new THREE.BoxGeometry(4.6, 0.45, 0.9), v.startsWith('R') ? mat.blue : mat.red);
    lev.position.x = 1.8; lev.castShadow = true; piv.add(lev);
    levers[v] = piv;
  }

  // Swagelok sensor tees + S-model transducers pointing up
  const sensorTop = {};
  for (const s of ['P1', 'P2']) {
    const p = xy(s);
    box(2.2, 2.2, 2.2, mat.steel, p.x, p.y, p.z);
    const body = add(new THREE.Mesh(new THREE.CylinderGeometry(1.35, 1.35, 8.5, 28), mat.steel)); body.position.set(p.x, p.y + 1.1 + 4.25 + 1.0, p.z);
    const hex = add(new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 1.2, 6), mat.steel)); hex.position.set(p.x, p.y + 1.6, p.z);
    const con = add(new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 1.6, 16), mat.black)); con.position.set(p.x, p.y + 11.2, p.z);
    sensorTop[s] = new THREE.Vector3(p.x, p.y + 12, p.z);
  }

  // leak taps: tee branch → ½" mini valve → tube over the table edge into the bucket
  const tapRoute = {
    L1: (p) => [p, new THREE.Vector3(p.x, YP + 0.2, p.z + 3.5), new THREE.Vector3(p.x - 1, YP + 2.6, p.z + 15.4), new THREE.Vector3(p.x - 1, YP + 0.8, 36.5), new THREE.Vector3(p.x, YP - 6, 40.5), new THREE.Vector3(p.x + 0.5, 58, 43)],
    L2: (p) => [p, new THREE.Vector3(p.x, YP + 0.2, p.z + 3.5), new THREE.Vector3(p.x + 0.5, YP + 0.4, 34.5), new THREE.Vector3(p.x + 1, YP - 5, 39.5), new THREE.Vector3(p.x + 2.5, 60, 44)],
    L3: (p) => [p, new THREE.Vector3(p.x, YP + 0.2, p.z + 3.5), new THREE.Vector3(p.x - 2, YP + 0.4, 34.5), new THREE.Vector3(p.x - 4, YP - 5, 39.5), new THREE.Vector3(p.x - 6, 60, 45)],
  };
  const taps = {};
  for (const t of ['L1', 'L2', 'L3']) {
    const p = xy('T' + t);
    const pts = tapRoute[t](p);
    const vpos = pts[0].clone().lerp(pts[1], 0.75);
    cylBetween(p, vpos, 0.75, mat.fitting);
    const vb = cylBetween(vpos, pts[1].clone().add(new THREE.Vector3(0, 0, 1.6)), 1.0, mat.brass);
    const piv = new THREE.Group(); piv.position.set(vpos.x, vpos.y + 1.6, vpos.z + 0.8); scene.add(piv);
    const lev = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.4, 3.4), mat.red); lev.position.z = 1.4; lev.castShadow = true; piv.add(lev);
    tube(pts.slice(1), 0.8, mat.black, 48);
    const end = pts[pts.length - 1];
    const cap = add(new THREE.Mesh(new THREE.CylinderGeometry(0.95, 0.95, 1.2, 18), mat.red)); cap.position.set(end.x, end.y - 0.5, end.z);
    taps[t] = { lever: piv, end: end.clone().add(new THREE.Vector3(0, -1.2, 0)), cap, valve: vpos.clone() };
  }

  // return pipe: right corner → table edge → into the bucket
  const t1 = xy('T1');
  const retPts = [t1, new THREE.Vector3(t1.x, YP, t1.z + 4), new THREE.Vector3(t1.x - 1, YP - 0.2, 35.5), new THREE.Vector3(t1.x - 6, YP - 8, 41), new THREE.Vector3(BUCKET.x + 9, 50, BUCKET.z - 3), new THREE.Vector3(BUCKET.x + 7, 42, BUCKET.z)];
  tube(retPts, R_PE, mat.black, 80);
  const retEnd = retPts[retPts.length - 1].clone().add(new THREE.Vector3(0, -1, 0));

  // bucket + water
  const bucket = add(new THREE.Mesh(new THREE.CylinderGeometry(BUCKET.rTop, BUCKET.rBot, BUCKET.h, 48, 1, true), mat.bucket), false);
  bucket.position.set(BUCKET.x, BUCKET.h / 2, BUCKET.z);
  const bb = add(new THREE.Mesh(new THREE.CircleGeometry(BUCKET.rBot, 48), mat.bucket)); bb.rotation.x = -Math.PI / 2; bb.position.set(BUCKET.x, 0.2, BUCKET.z);
  const rim = add(new THREE.Mesh(new THREE.TorusGeometry(BUCKET.rTop, 0.5, 10, 64), M({ color: '#e8e8e2', roughness: 0.5 }))); rim.rotation.x = Math.PI / 2; rim.position.set(BUCKET.x, BUCKET.h, BUCKET.z);
  const rWater = BUCKET.rBot + (BUCKET.rTop - BUCKET.rBot) * BUCKET.water / BUCKET.h - 0.3;
  const water = new THREE.Mesh(new THREE.CylinderGeometry(rWater, BUCKET.rBot - 0.3, BUCKET.water, 48), mat.water);
  water.position.set(BUCKET.x, BUCKET.water / 2 + 0.2, BUCKET.z); scene.add(water);

  // R365 pump on the floor beside the bucket (kept dry: it is not submersible)
  const pg = new THREE.Group(); pg.position.set(PUMP.x, 0, PUMP.z); scene.add(pg);
  const head = new THREE.Mesh(new THREE.BoxGeometry(4.2, 4.0, 4.0), mat.black); head.position.set(0, 2.2, 0); head.castShadow = true; pg.add(head);
  const motor = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.4, 5.2, 24), mat.motor); motor.rotation.z = Math.PI / 2; motor.position.set(-4.7, 2.2, 0); motor.castShadow = true; pg.add(motor);
  const foot = new THREE.Mesh(new THREE.BoxGeometry(9, 0.4, 5), mat.black); foot.position.set(-2.2, 0.2, 0); pg.add(foot);
  for (const dz of [-1.0, 1.0]) { const barb = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 2.2, 12), mat.black); barb.rotation.z = Math.PI / 2; barb.position.set(3.1, 2.6, dz); pg.add(barb); }
  const pOut = new THREE.Vector3(PUMP.x + 4.2, 2.6, PUMP.z - 1), pSuc = new THREE.Vector3(PUMP.x + 4.2, 2.6, PUMP.z + 1);
  // soft hose (1 m) pump → board inlet; suction tube pump → bucket
  const hosePts = [pOut, new THREE.Vector3(PUMP.x + 8, 4, PUMP.z - 6), new THREE.Vector3(-34, 40, 34), new THREE.Vector3(-31, YP + 1, 22), new THREE.Vector3(pIn.x - 6, YP, pIn.z), new THREE.Vector3(pIn.x - 2, YP, pIn.z)];
  const hoseMat = M({ color: '#ffffff', roughness: 0.15, transparent: true, opacity: 0.6, vertexColors: true });
  const hose = tube(hosePts, 0.55, hoseMat, 100);
  { const n = hose.geometry.attributes.position.count; hose.geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(n * 3).fill(0.85), 3));
    hose.userData.frac = Float32Array.from({ length: n }, (_, i) => Math.floor(i / 13) / 100); }
  tube([pSuc, new THREE.Vector3(PUMP.x + 9, 4, PUMP.z + 2), new THREE.Vector3(BUCKET.x - BUCKET.rTop + 1, BUCKET.h + 3, BUCKET.z - 1), new THREE.Vector3(BUCKET.x - 6, 12, BUCKET.z), new THREE.Vector3(BUCKET.x - 4, 2, BUCKET.z)], 0.55, mat.hose, 60);

  // electronics box: ESP32 + ADS1115 + divider breadboard, clear lid
  box(BOX.w, 0.4, BOX.d, M({ color: '#c9cbd0', roughness: 0.6 }), BOX.x, TABLE.h + 0.2, BOX.z);
  for (const [w, d, x, z] of [[BOX.w, 0.3, 0, -BOX.d / 2], [BOX.w, 0.3, 0, BOX.d / 2], [0.3, BOX.d, -BOX.w / 2, 0], [0.3, BOX.d, BOX.w / 2, 0]]) box(w, BOX.h, d, mat.boxGrey, BOX.x + x, TABLE.h + BOX.h / 2, BOX.z + z);
  box(5.2, 0.25, 2.8, mat.pcbBlack, BOX.x - 3.2, TABLE.h + 0.7, BOX.z - 2.2);
  box(1.8, 0.35, 1.6, mat.steel, BOX.x - 4.6, TABLE.h + 1.0, BOX.z - 2.2);
  box(2.8, 0.25, 1.8, mat.pcbBlue, BOX.x + 3.6, TABLE.h + 0.7, BOX.z - 2.4);
  box(8.0, 0.8, 4.0, mat.breadboard, BOX.x + 1.0, TABLE.h + 0.8, BOX.z + 2.2);
  for (let i = 0; i < 4; i++) box(0.9, 0.35, 0.3, M({ color: ['#c9a227', '#8b5a2b', '#c9a227', '#8b5a2b'][i], roughness: 0.6 }), BOX.x - 1.5 + i * 1.6, TABLE.h + 1.35, BOX.z + 2.2);
  const boxIn = (dz) => new THREE.Vector3(BOX.x - BOX.w / 2 + 0.5, TABLE.h + 3.5, BOX.z + dz);
  for (const [s, dz] of [['P1', -3], ['P2', -1]]) { const a = sensorTop[s]; tube([a, a.clone().add(new THREE.Vector3(0, 6, 0)), new THREE.Vector3((a.x + BOX.x) / 2, a.y + 6, (a.z + BOX.z) / 2), boxIn(dz)], 0.28, mat.cable, 60); }
  tube([fcap.position.clone().add(new THREE.Vector3(0, 0.7, 0)), fcap.position.clone().add(new THREE.Vector3(0, 6, -4)), new THREE.Vector3(20, YP + 9, -3), boxIn(1.5)], 0.22, mat.cableRed, 80);

  // two adapters (12 V pump, 24 V sensors) and their cables
  box(7, 3.4, 4.5, mat.black, 48, TABLE.h + 1.7, -22); box(7, 3.4, 4.5, mat.black, 59, TABLE.h + 1.7, -22);
  tube([new THREE.Vector3(59, TABLE.h + 2, -19.8), new THREE.Vector3(58, TABLE.h + 1, -8), boxIn(3).add(new THREE.Vector3(BOX.w, 0, 0))], 0.3, mat.cable, 40);
  tube([new THREE.Vector3(48, TABLE.h + 2, -19.8), new THREE.Vector3(66, TABLE.h + 1, -10), new THREE.Vector3(69, TABLE.h + 0.5, 30), new THREE.Vector3(68, 40, 46), new THREE.Vector3(20, 2, 70), new THREE.Vector3(PUMP.x - 6, 2.2, PUMP.z + 4), new THREE.Vector3(PUMP.x - 7.3, 2.2, PUMP.z)], 0.3, mat.cable, 120);

  // laptop with a live dashboard screen
  const lg = new THREE.Group(); lg.position.set(-48, TABLE.h, -6); lg.rotation.y = 0.35; scene.add(lg);
  const base = new THREE.Mesh(new THREE.BoxGeometry(32, 1.2, 22), mat.laptop); base.position.y = 0.6; base.castShadow = true; lg.add(base);
  const kb = new THREE.Mesh(new THREE.PlaneGeometry(27, 10), M({ color: '#2c2e33', roughness: 0.8 })); kb.rotation.x = -Math.PI / 2; kb.position.set(0, 1.22, -1.5); lg.add(kb);
  const scr = document.createElement('canvas'); scr.width = 640; scr.height = 400;
  const scrTex = new THREE.CanvasTexture(scr); scrTex.colorSpace = THREE.SRGBColorSpace;
  const lid = new THREE.Group(); lid.position.set(0, 1.2, -11); lid.rotation.x = -0.28; lg.add(lid);
  const lidBack = new THREE.Mesh(new THREE.BoxGeometry(32, 21, 0.8), mat.laptop); lidBack.position.y = 10.5; lidBack.castShadow = true; lid.add(lidBack);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(29.5, 18.4), new THREE.MeshBasicMaterial({ map: scrTex })); screen.position.set(0, 10.6, 0.45); lid.add(screen);

  // ── water particles (leaks and return) ──
  const NPART = 900;
  const pgeo = new THREE.BufferGeometry();
  const ppos = new Float32Array(NPART * 3).fill(-999), pvel = new Float32Array(NPART * 3), plive = new Float32Array(NPART);
  pgeo.setAttribute('position', new THREE.BufferAttribute(ppos, 3));
  const pts = new THREE.Points(pgeo, new THREE.PointsMaterial({ color: '#3d8fd1', size: 0.9, transparent: true, opacity: 0.85 }));
  scene.add(pts);
  let pnext = 0;
  function emit(at, rate, dt) {
    let n = rate * dt + Math.random();
    n = Math.floor(n);
    for (let i = 0; i < n; i++) {
      const k = pnext; pnext = (pnext + 1) % NPART;
      ppos[3 * k] = at.x + (Math.random() - 0.5) * 0.6; ppos[3 * k + 1] = at.y; ppos[3 * k + 2] = at.z + (Math.random() - 0.5) * 0.6;
      pvel[3 * k] = (Math.random() - 0.5) * 3; pvel[3 * k + 1] = -20 - Math.random() * 10; pvel[3 * k + 2] = (Math.random() - 0.5) * 3; plive[k] = 1;
    }
  }
  function stepParticles(dt) {
    for (let k = 0; k < NPART; k++) {
      if (!plive[k]) continue;
      pvel[3 * k + 1] -= 981 * dt;
      ppos[3 * k] += pvel[3 * k] * dt; ppos[3 * k + 1] += pvel[3 * k + 1] * dt; ppos[3 * k + 2] += pvel[3 * k + 2] * dt;
      if (ppos[3 * k + 1] < BUCKET.water) { plive[k] = 0; ppos[3 * k + 1] = -999; }
    }
    pgeo.attributes.position.needsUpdate = true;
  }

  // ── labels (HTML overlay) ──
  const labLayer = document.createElement('div'); labLayer.className = 'lab3d-layer'; host.appendChild(labLayer);
  const labels = [];
  function label(text, anchor, cls = '', near = 0) { const d = document.createElement('div'); d.className = 'lab3d ' + cls; d.textContent = text; labLayer.appendChild(d); const L = { d, a: anchor, near }; labels.push(L); return L; }
  const lP1 = label('P1', sensorTop.P1.clone().add(new THREE.Vector3(0, 3, 0)), 'strong');
  const lP2 = label('P2', sensorTop.P2.clone().add(new THREE.Vector3(0, 3, 0)), 'strong');
  const lF0 = label('F0', fcap.position.clone().add(new THREE.Vector3(0, 3, 0)), 'strong');
  const lV = {}; for (const v of ['R1', 'R2', 'V1', 'V2']) lV[v] = label(v, xy(v).add(new THREE.Vector3(0, 5.5, 0)), '', 150);
  const lT = {}; for (const t of ['L1', 'L2', 'L3']) lT[t] = label(t, taps[t].valve.clone().add(new THREE.Vector3(0, 4.5, 0)), '', 150);
  label('R365 pump (12 V)', new THREE.Vector3(PUMP.x - 2, 9, PUMP.z));
  label('bucket 20 L', new THREE.Vector3(BUCKET.x, BUCKET.h + 4, BUCKET.z + 8));
  label('ESP32 + ADS1115 + dividers', new THREE.Vector3(BOX.x, TABLE.h + 8, BOX.z));
  label('12 V + 24 V adapters', new THREE.Vector3(53.5, TABLE.h + 6.5, -22));
  label('laptop: dashboard', new THREE.Vector3(-48, TABLE.h + 25, -12));
  const tmpV = new THREE.Vector3();
  function placeLabels() {
    const w = W(), h = H();
    for (const L of labels) {
      const close0 = !L.near || L.d.classList.contains('alert') || camera.position.distanceTo(L.a) < L.near;
      tmpV.copy(L.a).project(camera);
      const close = close0;
      const vis = tmpV.z < 1 && Math.abs(tmpV.x) < 1.05 && Math.abs(tmpV.y) < 1.05 && ui.labels() && close;
      L.d.style.display = vis ? 'block' : 'none';
      if (vis) L.d.style.transform = `translate(-50%,-100%) translate(${(tmpV.x + 1) / 2 * w}px,${(1 - tmpV.y) / 2 * h}px)`;
    }
  }

  // ── state from the twin ──
  const cm = BD.cmap.map(c => new THREE.Color(c));
  const pColor = (p) => { const u = Math.max(0, Math.min(1, p / 1.2)) * (cm.length - 1), i = Math.min(cm.length - 2, Math.floor(u)); return cm[i].clone().lerp(cm[i + 1], u - i); };
  const nN = BD.nodes.length;
  let cur = null, leak = 'none', flows = [], wave = null;
  const steelC = new THREE.Color('#c9ced3'), blackC = new THREE.Color('#2a2b2e');
  function paint(mesh, fn) {          // fn(frac along the pipe, 0 = start node) -> THREE.Color
    const col = mesh.geometry.attributes.color, fr = mesh.userData.frac;
    for (let i = 0; i < fr.length; i++) { const c = fn(fr[i]); col.setXYZ(i, c.r, c.g, c.b); }
    col.needsUpdate = true;
  }
  const NEG = new THREE.Color('#2a78d6'), ZERO = new THREE.Color('#e6e5e0'), POS = new THREE.Color('#d03b3b');
  const dColor = (x) => { const u = Math.max(-1, Math.min(1, x)); return u < 0 ? ZERO.clone().lerp(NEG, -u) : ZERO.clone().lerp(POS, u); };
  function interp(samples, f) {       // samples: [[frac, value], ...] sorted
    for (let i = 1; i < samples.length; i++) if (f <= samples[i][0]) { const [f0, v0] = samples[i - 1], [f1, v1] = samples[i]; return v0 + (v1 - v0) * (f - f0) / Math.max(f1 - f0, 1e-9); }
    return samples[samples.length - 1][1];
  }
  let WV = null;                      // wave data index
  function initWaves(W) {
    const idx = {}; W.nodes.forEach((n, i) => idx[n] = i); W.mids.forEach((m, i) => idx[m] = W.nodes.length + i);
    pipes.forEach(p => { p.wave = [[0, idx[p.a]], ...(idx[p.id + '@0.5'] !== undefined ? [[0.5, idx[p.id + '@0.5']]] : []), [1, idx[p.b]]]; });
    hose.userData.wave = [[0, idx['PUMP_OUT']], ...[0.2, 0.4, 0.6, 0.8].map(f => [f, idx['HOSE@' + f]]), [1, idx['IN']]];
    WV = { W, idx };
  }
  function paintWave(ev, fi, scale) {
    const dh = ev.dh, sc = scale || ev.scale || 1;
    const val = (j) => dh[j][fi] / sc;
    pipes.forEach(p => { if (p.mesh.visible) paint(p.mesh, f => dColor(interp(p.wave.map(([ff, j]) => [ff, val(j)]), f))); });
    paint(hose, f => dColor(interp(hose.userData.wave.map(([ff, j]) => [ff, val(j)]), f)));
  }
  function paintSteady(s) {
    const colorMode = ui.colours();
    pipes.forEach(({ mesh, a, b, ss }) => {
      const ia = BD.nodes.indexOf(a), ib = BD.nodes.indexOf(b);
      if (ss) { paint(mesh, () => steelC); return; }
      if (!colorMode) { paint(mesh, () => blackC); return; }
      const ca = pColor(s[6 + ia]), cb = pColor(s[6 + ib]);
      paint(mesh, f => ca.clone().lerp(cb, f));
    });
    paint(hose, () => new THREE.Color('#d6ecf5'));
  }
  function setState(s, h, setting) {
    cur = s; leak = setting.leak; flows = s.slice(6 + nN);
    if (!wave) paintSteady(s);
    const ang = (deg) => -THREE.MathUtils.degToRad(Math.min(90, deg));
    levers.R1.rotation.y = ang(setting.r); levers.R2.rotation.y = ang(setting.r);
    levers.V1.rotation.y = ang(setting.v); levers.V2.rotation.y = ang(setting.v);
    for (const t of ['L1', 'L2', 'L3']) {
      const on = t === leak;
      taps[t].lever.rotation.y = on ? 0 : -Math.PI / 2;
      taps[t].cap.visible = on;
      lT[t].d.textContent = on ? `${t} leaking ${s[3].toFixed(3)} L/min` : `${t} shut`;
      lT[t].d.classList.toggle('alert', on);
    }
    if (!wave) { lP1.d.textContent = `P1 ${s[0].toFixed(3)} bar`; lP2.d.textContent = `P2 ${s[1].toFixed(3)} bar`; }
    lF0.d.textContent = `F0 ${s[2].toFixed(2)} L/min`;
    lV.R1.d.textContent = `R1 ${setting.r}°`; lV.R2.d.textContent = `R2 ${setting.r}°`; lV.V1.d.textContent = `V1 ${setting.v.toFixed(1)}°`; lV.V2.d.textContent = `V2 ${setting.v.toFixed(1)}°`;
    drawScreen(s, h, setting);
  }
  function drawScreen(s, h, setting) {
    const g = scr.getContext('2d');
    g.fillStyle = '#0f1720'; g.fillRect(0, 0, 640, 400);
    g.fillStyle = '#e8eef5'; g.font = '600 26px system-ui,sans-serif'; g.fillText('HydroPin bench', 28, 46);
    g.font = '15px system-ui,sans-serif'; g.fillStyle = '#93a3b5'; g.fillText('MQTT hydropin/bench · 1-s means', 28, 72);
    const card = (x, y, lab, val, unit) => { g.fillStyle = '#18232f'; g.fillRect(x, y, 180, 96); g.fillStyle = '#93a3b5'; g.font = '15px system-ui'; g.fillText(lab, x + 14, y + 26); g.fillStyle = '#ffffff'; g.font = '600 34px system-ui'; g.fillText(val, x + 14, y + 68); g.fillStyle = '#93a3b5'; g.font = '15px system-ui'; g.fillText(unit, x + 14, y + 88); };
    card(28, 96, 'P1', s[0].toFixed(3), 'bar'); card(230, 96, 'P2', s[1].toFixed(3), 'bar'); card(432, 96, 'F0', s[2].toFixed(2), 'L/min');
    const d1 = (s[0] - h[0]) * 1000, d2 = (s[1] - h[1]) * 1000;
    const det = setting.leak !== 'none' && (Math.abs(d1) > BD.thr.p1 || Math.abs(d1 - d2) > BD.thr.diff);
    g.fillStyle = det ? '#5c1d1d' : '#163a26'; g.fillRect(28, 222, 584, 64);
    g.fillStyle = det ? '#ffb4b4' : '#a6e3b8'; g.font = '600 24px system-ui';
    g.fillText(det ? (d1 < d2 ? '■ LEAK – branch A (L1)' : '■ LEAK – branch B (L2 or L3)') : '● no leak detected', 46, 263);
    g.fillStyle = '#93a3b5'; g.font = '16px system-ui';
    g.fillText(`ΔP1 ${d1.toFixed(1)} mbar · ΔP2 ${d2.toFixed(1)} mbar · ΔF0 ${(s[2] - h[2]).toFixed(3)} L/min`, 28, 320);
    g.fillText(`R1 = R2 ${setting.r}° · V1 = V2 ${setting.v.toFixed(1)}° · highest pressure ${s[5].toFixed(2)} bar`, 28, 348);
    scrTex.needsUpdate = true;
  }

  // ── live mode (dashboard): the readings and the detector come from the backend's frames; the twin
  //    only supplies what the bench does not measure (pressure along each pipe, how the flow splits).
  //    L = null (no data) or { p1, p2, f0, leakLpm, twin: twin state row, setting: {r, v},
  //    taps: { L1: { p, open, suspect }, ... }, status: { text, kind: 'ok'|'watch'|'leak'|'idle' } }
  const num = (x, d) => (x === null || x === undefined || !Number.isFinite(x)) ? '–' : x.toFixed(d);
  function setLive(L) {
    wave = null;
    const ang = (deg) => -THREE.MathUtils.degToRad(Math.min(90, deg));
    if (!L) {
      cur = null; leak = 'none'; flows = [];
      pipes.forEach(({ mesh, ss }) => paint(mesh, () => (ss ? steelC : blackC)));
      lP1.d.textContent = 'P1 –'; lP2.d.textContent = 'P2 –'; lF0.d.textContent = 'F0 –';
      for (const t of ['L1', 'L2', 'L3']) {
        taps[t].lever.rotation.y = -Math.PI / 2; taps[t].cap.visible = false;
        lT[t].d.textContent = t; lT[t].d.classList.remove('alert');
      }
      drawLive(null);
      return;
    }
    const s = L.twin.slice();
    const k = s[2] > 1e-6 && L.f0 > 0 ? L.f0 / s[2] : 0;      // twin flows scaled to the measured F0
    cur = s; cur[3] = L.leakLpm || 0; cur[4] = Math.max(0, (L.f0 || 0) - cur[3]);
    flows = s.slice(6 + nN).map((q) => q * k);
    paintSteady(s);
    leak = 'none';
    for (const t of ['L1', 'L2', 'L3']) {
      const T = L.taps[t] || {}, on = !!T.open;
      if (on) leak = t;
      taps[t].lever.rotation.y = on ? 0 : -Math.PI / 2;
      taps[t].cap.visible = on;
      lT[t].d.textContent = on ? `${t} leaking ${num(L.leakLpm, 2)} L/min`
        : T.suspect ? `${t} suspected ${Math.round(100 * T.p)} %` : t;
      lT[t].d.classList.toggle('alert', on || !!T.suspect);
    }
    if (L.setting) {
      levers.R1.rotation.y = ang(L.setting.r); levers.R2.rotation.y = ang(L.setting.r);
      levers.V1.rotation.y = ang(L.setting.v); levers.V2.rotation.y = ang(L.setting.v);
    }
    for (const v of ['R1', 'R2', 'V1', 'V2']) lV[v].d.textContent = v;   // valve angles are not measured live
    lP1.d.textContent = `P1 ${num(L.p1, 3)} bar`;
    lP2.d.textContent = `P2 ${num(L.p2, 3)} bar`;
    lF0.d.textContent = `F0 ${num(L.f0, 2)} L/min`;
    drawLive(L);
  }
  function drawLive(L) {
    const g = scr.getContext('2d');
    g.fillStyle = '#0f1a15'; g.fillRect(0, 0, 640, 400);
    g.fillStyle = '#e6efe9'; g.font = '600 26px system-ui,sans-serif'; g.fillText('HydroPin bench', 28, 46);
    g.font = '15px system-ui,sans-serif'; g.fillStyle = '#93a59b'; g.fillText(L ? 'live from the backend' : 'waiting for data', 28, 72);
    const card = (x, y, lab, val, unit) => { g.fillStyle = '#15231c'; g.fillRect(x, y, 180, 96); g.fillStyle = '#93a59b'; g.font = '15px system-ui'; g.fillText(lab, x + 14, y + 26); g.fillStyle = '#ffffff'; g.font = '600 34px system-ui'; g.fillText(val, x + 14, y + 68); g.fillStyle = '#93a59b'; g.font = '15px system-ui'; g.fillText(unit, x + 14, y + 88); };
    card(28, 96, 'P1', L ? num(L.p1, 3) : '–', 'bar'); card(230, 96, 'P2', L ? num(L.p2, 3) : '–', 'bar'); card(432, 96, 'F0', L ? num(L.f0, 2) : '–', 'L/min');
    const kind = L && L.status ? L.status.kind : 'idle';
    const [bgc, fgc] = { ok: ['#173826', '#86efac'], watch: ['#3a2c14', '#fcd34d'], leak: ['#4a1d1d', '#fca5a5'], idle: ['#1d2b24', '#93a59b'] }[kind];
    g.fillStyle = bgc; g.fillRect(28, 222, 584, 64);
    g.fillStyle = fgc; g.font = '600 24px system-ui';
    g.fillText(L && L.status ? L.status.text : 'Waiting for bench data', 46, 263);
    scrTex.needsUpdate = true;
  }

  // ── loop ──
  let last = performance.now(), running = true;
  function frame(now) {
    if (!running) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    controls.autoRotate = ui.rotate(); controls.autoRotateSpeed = 0.6;
    controls.update();
    if (cur) {
      // pipe stripes move at the real mean velocity: v = Q / A  (cm/s), 1 L/min = 16.67 cm³/s
      const A = Math.PI * 0.68 * 0.68;
      pipes.forEach(({ tex, k }) => { const v = flows[k] * 16.667 / A; tex.offset.y -= v * dt / 3; });
      for (const t of ['L1', 'L2', 'L3']) if (t === leak) emit(taps[t].end, 60 + 900 * cur[3], dt);
      if (cur[4] > 0.01) emit(retEnd, 40 + 260 * cur[4], dt);     // no return stream with the pump off
    }
    stepParticles(dt);
    renderer.render(scene, camera);
    placeLabels();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  new ResizeObserver(() => { renderer.setSize(W(), H()); camera.aspect = W() / H(); camera.updateProjectionMatrix(); }).observe(host);

  return {
    setState,
    setLive,
    initWaves,
    setWave(ev, fi, scale) {          // ev = null leaves wave mode; scale in mm of water
      wave = ev;
      if (!ev) { if (cur) paintSteady(cur); return; }
      paintWave(ev, fi, scale);
      const i1 = WV.idx['P1'], i2 = WV.idx['P2'];
      const d1 = ev.dh[i1][fi] / 10.197, d2 = ev.dh[i2][fi] / 10.197;      // mm of water → mbar
      lP1.d.textContent = `P1 ${(ev.p0[0] + d1 / 1000).toFixed(3)} bar (${d1 >= 0 ? '+' : ''}${d1.toFixed(0)} mbar)`;
      lP2.d.textContent = `P2 ${(ev.p0[1] + d2 / 1000).toFixed(3)} bar (${d2 >= 0 ? '+' : ''}${d2.toFixed(0)} mbar)`;
    },
    home() { camera.position.copy(HOME.pos); controls.target.copy(HOME.target); controls.update(); },
    view(name) {
      const V = { top: [[12, 205, 18], [12, 76, 14]], board: [[14, 128, 72], [12, 76, 14]], bucket: [[-60, 70, 140], [5, 30, 50]] }[name];
      if (V) { camera.position.set(...V[0]); controls.target.set(...V[1]); controls.update(); }
    },
    pause(p) { const was = running; running = !p; if (running && !was) { last = performance.now(); requestAnimationFrame(frame); } },
  };
}
