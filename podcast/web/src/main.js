// Virtual podcast studio: two VRM hosts at a desk, driven by a precomputed timeline.
// window.setup(timeline) loads everything; window.renderAt(t) draws the frame at time t.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const W = 1920, H = 1080;
const HANDTWIST = window.HANDTWIST ?? 1;
const NAVY = 0x1d2a5c, CORAL = 0xff6b4a, CREAM = 0xf6efe3;

// ---------- deterministic noise ----------
function hash(n) { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); }
function noise1(x) { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return (hash(i) * (1 - u) + hash(i + 1) * u) * 2 - 1; }
function fbm(x, seed) { return noise1(x + seed * 17.3) * 0.6 + noise1(x * 2.1 + seed * 5.1) * 0.3 + noise1(x * 4.3 + seed) * 0.1; }
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };
const lerp = (a, b, k) => a + (b - a) * k;

// ---------- canvas textures ----------
function canvasTex(w, h, draw) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  return t;
}
function woodTex(base = '#6b4a33', planks = 8, w = 1024, h = 1024) {
  return canvasTex(w, h, (g) => {
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    const ph = h / planks;
    for (let p = 0; p < planks; p++) {
      const shade = (hash(p * 3.1) - 0.5) * 30;
      g.fillStyle = `rgba(${shade > 0 ? 255 : 0},${shade > 0 ? 220 : 0},${shade > 0 ? 180 : 0},${Math.abs(shade) / 255})`;
      g.fillRect(0, p * ph, w, ph);
      for (let k = 0; k < 40; k++) {
        const y = p * ph + hash(p * 91 + k) * ph;
        g.strokeStyle = `rgba(30,18,10,${0.05 + hash(k * 7 + p) * 0.08})`;
        g.lineWidth = 1 + hash(k + p * 13) * 2;
        g.beginPath(); g.moveTo(0, y);
        for (let x = 0; x <= w; x += 32) g.lineTo(x, y + Math.sin(x * 0.01 + k) * 3);
        g.stroke();
      }
      g.fillStyle = 'rgba(20,10,5,0.5)'; g.fillRect(0, p * ph, w, 2);
      const off = hash(p * 5.7) * w; g.fillRect(off, p * ph, 2, ph);
    }
  });
}

// ---------- studio ----------
function buildStudio(scene) {
  const std = (o) => new THREE.MeshStandardMaterial(o);
  // floor
  const floorTex = woodTex('#3b2a20', 10); floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping; floorTex.repeat.set(3, 3);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(14, 14), std({ map: floorTex, roughness: 0.6 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  // rug
  const rug = new THREE.Mesh(new THREE.CircleGeometry(2.2, 64), std({ color: 0x2a3566, roughness: 1 }));
  rug.rotation.x = -Math.PI / 2; rug.position.set(0, 0.005, 0.2); rug.receiveShadow = true; scene.add(rug);
  const rugRing = new THREE.Mesh(new THREE.RingGeometry(2.0, 2.08, 64), std({ color: CORAL, roughness: 1 }));
  rugRing.rotation.x = -Math.PI / 2; rugRing.position.set(0, 0.008, 0.2); scene.add(rugRing);

  // back wall: navy paint
  const wall = new THREE.Mesh(new THREE.PlaneGeometry(14, 5), std({ color: 0x22305e, roughness: 0.9 }));
  wall.position.set(0, 2.5, -2.2); wall.receiveShadow = true; scene.add(wall);
  // side walls
  for (const s of [-1, 1]) {
    const sw = new THREE.Mesh(new THREE.PlaneGeometry(8, 5), std({ color: 0x1a2550, roughness: 0.9 }));
    sw.position.set(s * 4.2, 2.5, 1.5); sw.rotation.y = -s * Math.PI / 2; scene.add(sw);
  }
  // wooden slat panel behind the hosts
  const slatMat = std({ map: woodTex('#9a6b45', 1, 256, 256), roughness: 0.55 });
  for (let i = -18; i <= 18; i++) {
    const s = new THREE.Mesh(new THREE.BoxGeometry(0.05, 3.2, 0.04), slatMat);
    s.position.set(i * 0.085, 1.6, -2.15); s.castShadow = true; s.receiveShadow = true; scene.add(s);
  }
  // acoustic foam tiles on both sides
  const foamMat = [std({ color: 0x2b3870, roughness: 1 }), std({ color: 0x334280, roughness: 1 }), std({ color: 0x8a3b30, roughness: 1 })];
  for (const s of [-1, 1]) for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
    const m = foamMat[(r + c) % 7 === 0 ? 2 : (r + c) % 2];
    const tile = new THREE.Mesh(new RoundedBoxGeometry(0.42, 0.42, 0.08, 2, 0.03), m);
    tile.position.set(s * (2.25 + c * 0.46), 0.9 + r * 0.46, -2.14); tile.receiveShadow = true; scene.add(tile);
    // pyramid bumps
    for (let k = 0; k < 4; k++) {
      const b = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.07, 4), m);
      b.rotation.x = Math.PI / 2; b.rotation.y = Math.PI / 4;
      b.position.set(tile.position.x + (k % 2 ? 0.1 : -0.1), tile.position.y + (k < 2 ? 0.1 : -0.1), -2.06);
      scene.add(b);
    }
  }

  // neon sign
  const signTex = canvasTex(2048, 512, (g, w, h) => {
    g.clearRect(0, 0, w, h);
    g.font = '900 260px "Noto Sans CJK TC", "Noto Sans CJK SC", sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.shadowColor = '#ff6b4a'; g.shadowBlur = 60; g.fillStyle = '#ffd9cc';
    g.fillText('行為解碼', w / 2, h / 2 - 20);
    g.shadowBlur = 25; g.fillText('行為解碼', w / 2, h / 2 - 20);
    g.font = '700 70px "Noto Sans", sans-serif'; g.shadowColor = '#9fb4ff'; g.shadowBlur = 30; g.fillStyle = '#e6ecff';
    g.fillText('BEHAVIOR DECODED · PODCAST', w / 2, h / 2 + 175);
  });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 0.65), new THREE.MeshBasicMaterial({ map: signTex, transparent: true, toneMapped: false }));
  sign.position.set(0, 2.62, -2.09); scene.add(sign);
  const signLight = new THREE.PointLight(0xff7a5c, 2.2, 3.5, 2); signLight.position.set(0, 2.5, -1.7); scene.add(signLight);

  // shelves with books, plant and lamp, left and right
  const shelfMat = std({ map: woodTex('#7a5235', 2, 256, 256), roughness: 0.6 });
  const bookCols = [0x1d2a5c, 0xff6b4a, 0xf6efe3, 0x3c5a99, 0xd9a441, 0x5b7f6a, 0x8b4c3c, 0xe8e2d5];
  for (const s of [-1, 1]) {
    for (let r = 0; r < 3; r++) {
      const y = 0.55 + r * 0.62;
      const shelf = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.04, 0.32), shelfMat);
      shelf.position.set(s * 3.3, y, -1.95); shelf.castShadow = shelf.receiveShadow = true; scene.add(shelf);
      let x = s * 3.3 - 0.68;
      while (x < s * 3.3 + 0.62) {
        const seed = x * 13 + r * 7 + s;
        if (hash(seed) < 0.12) { x += 0.15; continue; }
        const bw = 0.03 + hash(seed + 1) * 0.04, bh = 0.2 + hash(seed + 2) * 0.16;
        const book = new THREE.Mesh(new THREE.BoxGeometry(bw, bh, 0.2 + hash(seed + 3) * 0.06),
          std({ color: bookCols[Math.floor(hash(seed + 4) * bookCols.length)], roughness: 0.8 }));
        book.position.set(x + bw / 2, y + 0.02 + bh / 2, -1.95);
        book.rotation.z = hash(seed + 5) < 0.1 ? 0.18 : 0;
        book.castShadow = true; scene.add(book);
        x += bw + 0.004;
      }
    }
    // plant on floor
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.17, 0.42, 32), std({ color: 0xe8e2d5, roughness: 0.7 }));
    pot.position.set(s * 2.2, 0.21, -1.6); pot.castShadow = true; scene.add(pot);
    const leafMat = std({ color: 0x3f6b4a, roughness: 0.7, side: THREE.DoubleSide });
    for (let k = 0; k < 26; k++) {
      const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 8), leafMat);
      leaf.scale.set(0.35, 1.2, 0.08);
      const a = k * 2.4, h = 0.55 + hash(k + s) * 0.75, rad = 0.06 + hash(k * 3 + s) * 0.18;
      leaf.position.set(s * 2.2 + Math.cos(a) * rad, h, -1.6 + Math.sin(a) * rad);
      leaf.rotation.set(Math.sin(a) * 0.6, a, Math.cos(a) * 0.6);
      leaf.castShadow = true; scene.add(leaf);
    }
    // floor lamp
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 1.6), std({ color: 0x222222, metalness: 0.8, roughness: 0.3 }));
    pole.position.set(s * 3.0, 0.8, -1.2); scene.add(pole);
    const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.24, 0.26, 32, 1, true),
      std({ color: 0xffe2b8, emissive: 0xffb36b, emissiveIntensity: 0.9, side: THREE.DoubleSide }));
    shade.position.set(s * 3.0, 1.68, -1.2); scene.add(shade);
    const lampLight = new THREE.PointLight(0xffb070, 1.6, 4, 2); lampLight.position.set(s * 3.0, 1.6, -1.1); scene.add(lampLight);
  }
  // string of warm bulbs across the top of the wall
  const bulbMat = new THREE.MeshBasicMaterial({ color: 0xffd28a, toneMapped: false });
  for (let i = 0; i < 26; i++) {
    const x = -4 + i * 0.32, y = 3.55 - Math.sin((i / 25) * Math.PI) * 0.28;
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.028, 10, 8), bulbMat);
    b.position.set(x, y, -2.05); scene.add(b);
  }

  // TV screen on the wall (topic card lives here too)
  const tvFrame = new THREE.Mesh(new RoundedBoxGeometry(1.5, 0.88, 0.05, 2, 0.02), std({ color: 0x111111, roughness: 0.4 }));
  tvFrame.position.set(0, 1.62, -2.08); scene.add(tvFrame);
  const tvCanvas = document.createElement('canvas'); tvCanvas.width = 960; tvCanvas.height = 540;
  const tvTex = new THREE.CanvasTexture(tvCanvas); tvTex.colorSpace = THREE.SRGBColorSpace;
  const tv = new THREE.Mesh(new THREE.PlaneGeometry(1.44, 0.81), new THREE.MeshBasicMaterial({ map: tvTex, toneMapped: false }));
  tv.position.set(0, 1.62, -2.05); scene.add(tv);

  // desk
  const deskTop = new THREE.Mesh(new RoundedBoxGeometry(2.6, 0.06, 0.95, 4, 0.025), std({ map: woodTex('#a77a52', 3), roughness: 0.45 }));
  deskTop.position.set(0, 0.74, -0.08); deskTop.castShadow = deskTop.receiveShadow = true; scene.add(deskTop);
  const front = new THREE.Mesh(new RoundedBoxGeometry(2.4, 0.66, 0.06, 2, 0.02), std({ color: NAVY, roughness: 0.7 }));
  front.position.set(0, 0.38, 0.32); front.castShadow = front.receiveShadow = true; scene.add(front);
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.03, 0.065), new THREE.MeshBasicMaterial({ color: CORAL }));
  stripe.position.set(0, 0.6, 0.32); scene.add(stripe);
  const logoTex = canvasTex(1024, 256, (g, w, h) => {
    g.fillStyle = '#f6efe3'; g.font = '900 120px "Noto Sans CJK TC", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('行為解碼', w / 2, h / 2);
  });
  const deskLogo = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.15), new THREE.MeshBasicMaterial({ map: logoTex, transparent: true }));
  deskLogo.position.set(0.85, 0.5, 0.355); deskLogo.scale.setScalar(0.6); scene.add(deskLogo);

  // props on the desk
  const mug = (x, z, col) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, 0.11, 24), std({ color: col, roughness: 0.4 }));
    m.position.set(x, 0.825, z); m.castShadow = true; scene.add(m);
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.03, 0.008, 8, 16), std({ color: col, roughness: 0.4 }));
    handle.position.set(x + 0.05, 0.83, z); scene.add(handle);
    const coffee = new THREE.Mesh(new THREE.CircleGeometry(0.04, 20), std({ color: 0x3a2214, roughness: 0.2 }));
    coffee.rotation.x = -Math.PI / 2; coffee.position.set(x, 0.872, z); scene.add(coffee);
  };
  mug(-0.78, 0.12, CORAL); mug(0.88, 0.1, CREAM);
  // tablet lying on the desk between the hosts
  const tab = new THREE.Mesh(new RoundedBoxGeometry(0.26, 0.012, 0.18, 2, 0.006), std({ color: 0x222228, metalness: 0.5, roughness: 0.3 }));
  tab.position.set(-0.3, 0.777, 0.1); tab.rotation.y = 0.3; scene.add(tab);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.23, 0.15), new THREE.MeshBasicMaterial({ color: 0x3c5a99 }));
  scr.rotation.set(-Math.PI / 2, 0, 0.3); scr.position.set(-0.3, 0.784, 0.1); scene.add(scr);
  // printed paper pages in front of host B
  const pageTex = canvasTex(256, 360, (g, w, h) => {
    g.fillStyle = '#fbf8f2'; g.fillRect(0, 0, w, h); g.fillStyle = '#1d2a5c'; g.fillRect(20, 24, 170, 14);
    for (let i = 0; i < 22; i++) { g.fillStyle = 'rgba(40,40,40,0.35)'; g.fillRect(20, 56 + i * 13, 200 - hash(i) * 50, 5); }
    g.fillStyle = '#ff6b4a'; g.fillRect(20, 200, 90, 50);
  });
  for (let k = 0; k < 3; k++) {
    const pg = new THREE.Mesh(new THREE.PlaneGeometry(0.21, 0.297), std({ map: pageTex, roughness: 0.9 }));
    pg.rotation.x = -Math.PI / 2; pg.rotation.z = -0.4 + k * 0.08;
    pg.position.set(0.3 + k * 0.01, 0.772 + k * 0.001, 0.12 - k * 0.01); pg.receiveShadow = true; scene.add(pg);
  }
  return { tvCanvas, tvTex };
}

// podcast microphone on a desk stand, aimed at a mouth
function buildMic(scene, pos, target) {
  const g = new THREE.Group();
  const metal = new THREE.MeshStandardMaterial({ color: 0x1b1b1f, metalness: 0.85, roughness: 0.3 });
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.09, 0.02, 32), metal); base.position.y = 0.01; g.add(base);
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.2), metal); pole.position.y = 0.1; g.add(pole);
  const head = new THREE.Group(); head.position.y = 0.21; g.add(head);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.032, 0.11, 8, 24), metal); body.rotation.x = Math.PI / 2; head.add(body);
  const grille = new THREE.Mesh(new THREE.SphereGeometry(0.036, 24, 16), new THREE.MeshStandardMaterial({ color: CORAL, roughness: 1 }));
  grille.position.z = 0.075; grille.scale.set(1, 1, 1.15); head.add(grille);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.035, 0.004, 8, 24), metal); ring.position.z = -0.02; head.add(ring);
  g.position.copy(pos); g.scale.setScalar(0.85); scene.add(g);
  const wp = new THREE.Vector3(); head.getWorldPosition(wp);
  head.lookAt(target);
  g.traverse((o) => { o.castShadow = true; });
  return g;
}

// ---------- hosts ----------
const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));

async function loadHost(url, opts) {
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  vrm.scene.traverse((o) => {
    o.frustumCulled = false;
    if (o.isMesh) { o.castShadow = true; if (opts.hide && opts.hide.some((h) => o.name.includes(h))) o.visible = false; }
  });
  if (opts.tint) vrm.scene.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)) {
      const t = opts.tint[m.name.replace(/ \(Outline\)$/, '')];
      if (t && m.color) { m.color.set(t); if (m.shadeColorFactor) m.shadeColorFactor.set(t).multiplyScalar(0.7); }
    }
  });
  return vrm;
}

const bone = (vrm, n) => vrm.humanoid.getNormalizedBoneNode(n);

// seated rest pose, then layered animation each frame
function applyPose(h, t, st) {
  const v = h.vrm, s = h.side; // side: -1 = left host (A), +1 = right host (B)
  const set = (n, x, y, z) => { const b = bone(v, n); if (b) b.rotation.set(x, y, z); };
  const sp = st.speak, gs = st.gesture, seed = h.seed;
  // legs: seated
  set('leftUpperLeg', -1.45, 0.08, 0.04); set('rightUpperLeg', -1.45, -0.08, -0.04);
  set('leftLowerLeg', 1.5, 0, 0); set('rightLowerLeg', 1.5, 0, 0);
  set('leftFoot', -0.1, 0, 0); set('rightFoot', -0.1, 0, 0);
  // torso: lean toward the desk, breathe, sway while talking
  const breath = Math.sin(t * 1.6 + seed) * 0.5 + 0.5;
  const sway = fbm(t * 0.35, seed) * 0.05 + fbm(t * 1.2, seed + 3) * 0.04 * sp;
  set('hips', 0, 0, 0);
  set('spine', 0.1 + breath * 0.015 + st.lean, sway * 0.6 + st.turn * 0.35, fbm(t * 0.3, seed + 9) * 0.03);
  set('chest', 0.04 + breath * 0.02, st.turn * 0.25, sway * 0.4);
  if (bone(v, 'upperChest')) set('upperChest', 0.02, st.turn * 0.1, 0);
  // head: nods tied to speech energy, look toward partner/camera
  const nod = fbm(t * 2.2, seed + 11) * 0.09 * sp + st.nod;
  const tilt = fbm(t * 0.5, seed + 21) * 0.08 + st.tilt;
  set('neck', 0.04 + nod * 0.4, st.turn * 0.25, tilt * 0.4);
  set('head', -0.03 + nod * 0.6 + fbm(t * 0.4, seed + 31) * 0.04, st.turn * 0.4 + fbm(t * 0.3, seed + 41) * 0.08, tilt * 0.6);
  // arms: two-bone IK toward hand targets given in the host's own frame (+Z forward, +X = host's left)
  v.scene.updateMatrixWorld(true);
  const deskY = 0.8 - v.scene.position.y;
  const shoulderY = h.shoulderLocalY;
  const near = s < 0 ? 'right' : 'left';   // arm nearer the partner gestures more
  const far = s < 0 ? 'left' : 'right';
  const k = (side) => (side === 'left' ? 1 : -1);
  const wob = (o, f = 1.3) => fbm(t * f, seed + o);
  const targets = {};
  for (const side of ['left', 'right']) {
    const g = side === near ? gs.main : gs.both;
    const rest = new THREE.Vector3(k(side) * 0.15, deskY + 0.04, h.L1 * 0.45 + h.L2 * 0.9 + (side === near ? 0.02 : 0));
    const up = new THREE.Vector3(k(side) * (0.2 + wob(51 + k(side)) * 0.07), shoulderY - h.L1 * 0.55 + wob(61 + k(side), 1.7) * 0.08, h.L1 * 0.35 + h.L2 * 0.8 + wob(71 + k(side)) * 0.05);
    let p = rest.clone().lerp(up, g);
    if (side === far && gs.wave > 0) p.lerp(new THREE.Vector3(k(side) * 0.32, shoulderY + 0.2, 0.22), gs.wave);
    targets[side] = { p, open: Math.max(g, side === far ? gs.wave : 0) };
  }
  for (const side of ['left', 'right']) {
    const { p, open } = targets[side];
    set(side + 'Shoulder', 0, 0, 0);
        solveArm(v, side, v.scene.localToWorld(p.clone()), v.scene.localToWorld(new THREE.Vector3(k(side) * 0.8, -0.6, -0.5)).sub(v.scene.getWorldPosition(new THREE.Vector3())));
    const kk = k(side);
    const waving = side === far ? gs.wave : 0;
    set(side + 'Hand', HANDTWIST * kk * open * 0.7, kk * (0.1 + waving * Math.sin(t * 10) * 0.5), -kk * 0.12);
    const curl = 0.45 - open * 0.38;
    for (const f of ['Index', 'Middle', 'Ring', 'Little']) {
      const extra = (f === 'Little' ? 0.12 : f === 'Ring' ? 0.06 : 0) + wob(91 + f.length, 0.7) * 0.05;
      for (const j of ['Proximal', 'Intermediate', 'Distal']) set(side + f + j, 0, 0, -kk * (curl + extra));
    }
    set(side + 'ThumbMetacarpal', 0, kk * 0.3, -kk * 0.1); set(side + 'ThumbProximal', 0, kk * 0.2, 0);
  }
}

const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _v = new THREE.Vector3(), _v2 = new THREE.Vector3();
// point bone `b` (normalized rig) so that its child lies along world direction `dir`
function aimBone(b, child, dir) {
  b.quaternion.identity(); b.updateMatrixWorld(true);
  const pq = b.parent.getWorldQuaternion(new THREE.Quaternion());
  const restDir = child.position.clone().normalize().applyQuaternion(pq);
  const wq = new THREE.Quaternion().setFromUnitVectors(restDir, dir.clone().normalize()).multiply(pq);
  b.quaternion.copy(pq.invert().multiply(wq));
  b.updateMatrixWorld(true);
}
function solveArm(v, side, wrist, pole) {
  const up = bone(v, side + 'UpperArm'), lo = bone(v, side + 'LowerArm'), hand = bone(v, side + 'Hand');
  const L1 = lo.position.length(), L2 = hand.position.length();
  const S = up.getWorldPosition(new THREE.Vector3());
  const d = wrist.clone().sub(S);
  const dist = Math.min(d.length(), (L1 + L2) * 0.995);
  const dn = d.normalize();
  const cosA = clamp((L1 * L1 + dist * dist - L2 * L2) / (2 * L1 * dist), -1, 1);
  const bend = pole.clone().sub(dn.clone().multiplyScalar(pole.dot(dn))).normalize();
  const E = S.clone().add(dn.clone().multiplyScalar(cosA * L1)).add(bend.multiplyScalar(Math.sqrt(1 - cosA * cosA) * L1));
  aimBone(up, lo, E.clone().sub(S));
  const W = S.clone().add(dn.multiplyScalar(dist));
  aimBone(lo, hand, W.sub(E));
}

// ---------- overlays (HTML) ----------
const $ = (id) => document.getElementById(id);

function drawTV(ctx, card, tl) {
  const w = 960, h = 540;
  ctx.fillStyle = '#f6efe3'; ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = '#1d2a5c'; ctx.fillRect(0, 0, w, 70);
  ctx.fillStyle = '#ff6b4a'; ctx.fillRect(0, 70, w, 8);
  ctx.font = '700 36px "Noto Sans CJK TC", sans-serif'; ctx.fillStyle = '#f6efe3'; ctx.textBaseline = 'middle';
  ctx.fillText('行為解碼 · 本集', 30, 36);
  ctx.fillStyle = '#1d2a5c'; ctx.font = '900 58px "Noto Sans CJK TC", sans-serif';
  const [l1, l2] = tl.title.split('，'); ctx.fillText(l1 + '，', 40, 190); ctx.fillText(l2 || '', 40, 270);
  ctx.font = '500 26px "Noto Sans", sans-serif'; ctx.fillStyle = '#555';
  ctx.fillText(tl.paper.venue, 40, 360);
  // little bar chart motif
  const bars = [0.4, 0.7, 0.55, 0.9, 0.62];
  bars.forEach((b, i) => { ctx.fillStyle = i === 3 ? '#ff6b4a' : '#1d2a5c'; ctx.fillRect(620 + i * 60, 470 - b * 300, 40, b * 300); });
}

const CARDS = {
  paper: (tl) => `<div class="kicker">本集論文</div><div class="ptitle">${tl.paper.title}</div>
    <div class="meta">${tl.paper.venue}</div><div class="meta">${tl.paper.authors}</div><div class="meta dim">${tl.paper.affil}</div>`,
  data: () => `<div class="kicker">資料</div><div class="big">約 150 萬篇</div><div class="sub">Change.org 上的請願</div>
    <div class="row"><span class="pill">2023/10/2</span> 上線「Write with AI」按鈕</div>`,
  design: () => `<div class="kicker">研究設計 · 差異中的差異</div>
    <div class="tl"><div class="lane"><b>美・英・加</b><div class="bar"><i style="left:30%"></i></div></div>
    <div class="lane"><b>澳洲</b><div class="bar"><i style="left:62%"></i></div></div>
    <div class="gapnote">晚 11 週上線 → 這段時間當對照組</div></div>`,
  text: () => `<div class="kicker">請願書的文字變了</div>
    <div class="stat"><span class="num">+49%</span><span class="lbl">字數中位數<br><small>約 110 → 164 個英文字</small></span></div>
    <div class="stat"><span class="num">+1.5</span><span class="lbl">閱讀難度（年級）</span></div>
    <div class="stat"><span class="num">+23%</span><span class="lbl">彼此的相似度</span></div>`,
  outcome: () => `<div class="kicker">可是成效沒有變好</div>
    <div class="stat"><span class="num down">−5.3</span><span class="lbl">拿到 ≥10 個連署的機率<br><small>百分點</small></span></div>
    <div class="stat"><span class="num dim">−2.5</span><span class="lbl">30 天內有留言的機率<br><small>百分點 · 統計上不顯著</small></span></div>`,
  repeat: () => `<div class="kicker">同一個人前後比</div><div class="big">4,611 人</div><div class="sub">AI 上線前後都發起過請願</div>
    <div class="row">有 AI 之後的那篇：<b>更長</b>，<b class="coral">成效更差</b></div>`,
  why: () => `<div class="kicker">可能的原因（作者推測，非定論）</div>
    <div class="row">① 大家用同一個工具 → 寫得越來越像</div><div class="row">② 請願變長，手機上沒人讀完</div>`,
  limits: () => `<div class="kicker">要小心的地方</div>
    <div class="row">只看 Change.org 一個平台</div><div class="row">只看 2023 年上線那段時間</div><div class="row">原因是推測，不是證明</div>`,
  takeaway: () => `<div class="kicker">一句話</div><div class="ptitle">AI 改變了我們寫什麼，<br>但不一定改變結果。</div>`,
};

// ---------- main ----------
let S = {};
window.setup = async (tl) => {
  const Q = window.QUALITY || { aa: true, shadow: 2048, scale: 1 };
  const renderer = new THREE.WebGLRenderer({ canvas: $('c'), antialias: Q.aa, preserveDrawingBuffer: true });
  renderer.setSize(W, H, false); renderer.setPixelRatio(Q.scale);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = Q.shadow > 1024 ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x141a33);
  scene.fog = new THREE.Fog(0x141a33, 6, 12);
  const studio = buildStudio(scene);

  // lights
  scene.add(new THREE.HemisphereLight(0xfff1e0, 0x2a2f55, 1.0));
  const key = new THREE.DirectionalLight(0xfff0dd, 2.3); key.position.set(-1.8, 3.2, 3.0); key.castShadow = true;
  key.shadow.mapSize.set(Q.shadow, Q.shadow); key.shadow.camera.left = -3; key.shadow.camera.right = 3; key.shadow.camera.top = 3; key.shadow.camera.bottom = -1;
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02; scene.add(key);
  const fill = new THREE.DirectionalLight(0xc8d4ff, 0.7); fill.position.set(2.5, 1.8, 2.5); scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffb59c, 1.4); rim.position.set(0, 2.5, -3); scene.add(rim);

  const A = await loadHost('models/anne.vrm', {
    tint: { Tops_01_CLOTH: '#f2e6d4' } });
  const B = await loadHost('models/kai.vrm', { hide: ['robo_arm'] });
  const hosts = { A: { vrm: A, side: -1, seed: 1.3 }, B: { vrm: B, side: 1, seed: 7.7 } };
  // place: seated behind the desk, angled toward each other
  for (const [k, h] of Object.entries(hosts)) {
    const g = h.vrm.scene; scene.add(g);
    const hy = bone(h.vrm, 'hips').getWorldPosition(new THREE.Vector3()).y;
    const sy = bone(h.vrm, 'leftUpperArm').getWorldPosition(new THREE.Vector3()).y;
    h.baseYaw = -h.side * 0.5;
    g.rotation.y = h.baseYaw;
    h.L1 = bone(h.vrm, 'leftLowerArm').position.length(); h.L2 = bone(h.vrm, 'leftHand').position.length();
    h.seatY = 0.8 + 0.8 * h.L1 - (sy - hy);
    g.position.set(h.side * 0.62, h.seatY - hy, -0.62);
    h.shoulderLocalY = sy;
    h.head = new THREE.Object3D(); scene.add(h.head);
  }
  // chairs
  for (const h of Object.values(hosts)) {
    const chair = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: 0x1b1b22, roughness: 0.6 });
    const seat = new THREE.Mesh(new RoundedBoxGeometry(0.5, 0.08, 0.5, 2, 0.03), mat); seat.position.y = 0.42; chair.add(seat);
    const back = new THREE.Mesh(new RoundedBoxGeometry(0.48, 0.6, 0.07, 2, 0.03), mat); back.position.set(0, 0.8, -0.25); back.rotation.x = -0.1; chair.add(back);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.4), new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.9, roughness: 0.3 })); post.position.y = 0.22; chair.add(post);
    chair.position.set(h.side * 0.62, h.seatY - 0.47, -0.7); chair.rotation.y = h.baseYaw; chair.traverse((o) => { o.castShadow = true; }); scene.add(chair);
  }
  // initial update so head bones exist in world space
  for (const h of Object.values(hosts)) { applyPose(h, 0, idleState()); h.vrm.update(0); }
  for (const h of Object.values(hosts)) {
    const hp = bone(h.vrm, 'head').getWorldPosition(new THREE.Vector3());
    h.headPos = hp;
    const mouth = hp.clone().add(new THREE.Vector3(0, -0.06, 0.06));
    const micPos = new THREE.Vector3(hp.x + h.side * 0.2, 0.77, hp.z + 0.36);
    buildMic(scene, micPos, mouth);
  }
  hosts.A.other = hosts.B; hosts.B.other = hosts.A;

  const camera = new THREE.PerspectiveCamera(32, W / H, 0.05, 50);
  const camTarget = new THREE.Object3D(); scene.add(camTarget);
  S = { renderer, scene, camera, camTarget, hosts, tl, studio, lastT: null, cardShown: null };
  drawTV(studio.tvCanvas.getContext('2d'), null, tl); studio.tvTex.needsUpdate = true;
  buildShots();
  return true;
};

function idleState() { return { speak: 0, lean: 0, turn: 0, nod: 0, tilt: 0, gesture: { main: 0, both: 0, wave: 0 } }; }

// camera shot list from the timeline
function buildShots() {
  const { tl } = S; const shots = [];
  shots.push({ start: 0, end: tl.intro + 0.4, kind: 'intro' });
  let cur = null;
  tl.lines.forEach((l, i) => {
    const dur = l.end - l.start;
    let kind;
    if (l.card) kind = l.spk === 'A' ? 'cardA' : 'cardB';
    else if (dur < 1.4) kind = 'wide';
    else kind = l.spk === 'A' ? 'A' : 'B';
    // occasionally hold the two-shot to keep the conversation feel
    if (!l.card && dur >= 1.4 && hash(i * 3.3) < 0.18) kind = 'wide2';
    const start = i === 0 ? tl.intro + 0.4 : Math.max(l.start - 0.12, shots[shots.length - 1].start + 0.6);
    if (cur && cur.kind === kind) { cur.end = l.end; return; }
    if (cur) cur.end = start;
    cur = { start, end: l.end, kind, idx: i };
    shots.push(cur);
  });
  cur.end = tl.duration - 2.6;
  shots.push({ start: tl.duration - 2.6, end: tl.duration + 1, kind: 'outro' });
  S.shots = shots;
}

function setCamera(t) {
  const { camera, hosts } = S;
  const shot = S.shots.find((s) => t >= s.start && t < s.end) || S.shots[S.shots.length - 1];
  const u = (t - shot.start) / Math.max(0.1, shot.end - shot.start);
  const drift = (a) => fbm(t * 0.15, a) * 0.02;
  const ha = hosts.A.headPos, hb = hosts.B.headPos;
  let pos, look, fov = 30;
  const mid = ha.clone().add(hb).multiplyScalar(0.5);
  switch (shot.kind) {
    case 'intro': { const k = smooth(u); pos = new THREE.Vector3(lerp(-1.2, 0, k), lerp(1.7, 1.35, k), lerp(4.6, 3.6, k)); look = new THREE.Vector3(0, lerp(1.5, 1.1, k), -0.6); fov = 34; break; }
    case 'outro': { const k = smooth(u); pos = new THREE.Vector3(0, lerp(1.3, 1.6, k), lerp(3.4, 4.6, k)); look = new THREE.Vector3(0, 1.2, -0.6); fov = 34; break; }
    case 'wide': case 'wide2': pos = new THREE.Vector3(drift(1) * 4, 1.3 + drift(2), 3.3 - u * 0.15); look = mid.clone().add(new THREE.Vector3(0, -0.12, 0)); fov = 30; break;
    case 'A': case 'B': case 'cardA': case 'cardB': {
      const me = shot.kind.endsWith('A') ? hosts.A : hosts.B;
      const hp = me.headPos;
      // camera on the partner's side, in front: 3/4 view of the speaker
      const side = -me.side;
      const card = shot.kind.startsWith('card');
      pos = new THREE.Vector3(hp.x + side * 0.7, hp.y + 0.05 + drift(3), hp.z + 1.9 - u * 0.1);
      look = hp.clone().add(new THREE.Vector3(card ? side * 0.25 : side * 0.06, -0.14, 0));
      fov = card ? 32 : 28;
      break;
    }
  }
  camera.fov = fov; camera.updateProjectionMatrix();
  camera.position.copy(pos); camera.lookAt(look);
  return shot;
}

function lineAt(t) { return S.tl.lines.find((l) => t >= l.start && t < l.end); }

function hostState(key, t) {
  const { tl } = S;
  const st = idleState();
  const f = Math.min(Math.floor(t * tl.fps), tl.mouth[key].length - 1);
  const m = tl.mouth[key][Math.max(0, f)] || [0, 0, 0, 0, 0];
  const energy = Math.min(1, (m[0] + m[1] + m[2] + m[3] + m[4]) * 1.6);
  // smoothed speaking activity over the last ~0.4 s
  let act = 0; for (let k = 0; k < 12; k++) { const mm = tl.mouth[key][Math.max(0, f - k)] || [0, 0, 0, 0, 0]; act += mm.reduce((a, b) => a + b, 0); }
  st.speak = Math.min(1, act / 12 * 2.5);
  st.mouth = m;
  // emotion / gesture from the current or most recent line of this speaker
  const lines = tl.lines;
  st.emo = {};
  for (const l of lines) {
    if (l.spk !== key) continue;
    const span = l.end - l.start;
    const w = smooth((t - l.start + 0.15) / 0.35) * (1 - smooth((t - l.end - 0.6) / 0.6));
    if (w <= 0) continue;
    if (l.emo) st.emo[l.emo] = Math.max(st.emo[l.emo] || 0, w * ({ surprised: 0.7, happy: 0.45 }[l.emo] || 0.6));
    if (l.gest) {
      const gw = smooth((t - l.start - 0.1) / 0.5) * (1 - smooth((t - l.end + 0.3) / 0.5));
      if (l.gest === 'both') st.gesture.both = Math.max(st.gesture.both, gw), st.gesture.main = Math.max(st.gesture.main, gw);
      else if (l.gest === 'wave') st.gesture.wave = Math.max(st.gesture.wave, smooth((t - l.end + 1.6) / 0.4) * (1 - smooth((t - l.end - 1.4) / 0.4)));
      else st.gesture.main = Math.max(st.gesture.main, gw * (l.gest === 'explain' ? 1 : 0.8));
    }
    if (span > 0) {}
  }
  // listener reactions: smile when partner jokes, nod on backchannels and at partner's sentence ends
  for (const l of lines) {
    if (l.spk === key) continue;
    if (l.emo === 'happy') {
      const w = smooth((t - l.start - 0.3) / 0.5) * (1 - smooth((t - l.end - 0.8) / 0.5));
      st.emo.happy = Math.max(st.emo.happy || 0, w * 0.3);
    }
    if (l.back && l.back.spk === key) {
      const d = t - l.back.start; if (d > -0.1 && d < 0.9) st.nod += Math.sin(clamp(d / 0.9) * Math.PI * 2) * 0.09;
    }
    const d = t - l.end; if (d > -0.3 && d < 0.6) st.nod += Math.sin(clamp((d + 0.3) / 0.9) * Math.PI) * 0.05;
  }
  // lean in a bit while talking, sit back slightly when listening
  st.lean = st.speak * 0.04;
  st.tilt = (st.emo.surprised || 0) * -0.06 + (st.emo.happy || 0) * 0.05;
  return st;
}

function blinkAt(seed, t) {
  // blink every 2-5 s, 0.16 s long; sometimes a double blink
  let tt = 0, i = 0;
  const period = (k) => 2 + hash(seed + k * 1.7) * 3;
  const cycle = 3.5; const base = Math.floor(t / cycle);
  for (let k = base - 1; k <= base; k++) {
    const bt = k * cycle + hash(seed + k) * 2.5;
    for (const off of [0, hash(seed + k * 9) < 0.2 ? 0.28 : -99]) {
      const d = t - (bt + off);
      if (d >= 0 && d < 0.16) return Math.sin((d / 0.16) * Math.PI);
    }
  }
  return 0;
}

window.renderAt = (t) => {
  const { renderer, scene, camera, hosts, tl } = S;
  const dt = S.lastT === null ? 1 / 30 : Math.max(0.0001, Math.min(0.1, t - S.lastT));
  S.lastT = t;
  const shot = setCamera(t);
  const cur = lineAt(t);
  for (const [k, h] of Object.entries(hosts)) {
    const st = hostState(k, t);
    // gaze: at partner while talking/listening, at camera sometimes when explaining in close-up
    const talking = cur && cur.spk === k;
    const toCam = talking && (shot.kind === k || shot.kind === 'card' + k) && hash(Math.floor(t / 2.7) + h.seed) < 0.35;
    const other = h.other.headPos;
    // turn body toward partner (they sit angled already), extra head turn
    const targetTurn = toCam ? h.side * 0.25 : -h.side * 0.1;
    h.turn = h.turn === undefined ? targetTurn : h.turn + (targetTurn - h.turn) * Math.min(1, dt * 4);
    st.turn = h.turn;
    applyPose(h, t, st);
    // look-at target
    const lookPos = toCam ? camera.position.clone() : other.clone().add(new THREE.Vector3(0, -0.03, 0));
    if (!h.lookObj) { h.lookObj = new THREE.Object3D(); scene.add(h.lookObj); h.vrm.lookAt.target = h.lookObj; h.lookObj.position.copy(lookPos); }
    h.lookObj.position.lerp(lookPos, Math.min(1, dt * 6));
    // saccades
    h.lookObj.position.x += fbm(t * 3, h.seed + 99) * 0.01;
    // expressions
    const em = h.vrm.expressionManager;
    const m = st.mouth;
    const happy = st.emo.happy || 0, sur = st.emo.surprised || 0, rel = st.emo.relaxed || 0, sad = st.emo.sad || 0;
    const mouthScale = 1 - happy * 0.3;
    em.setValue('aa', clamp(m[0] * 1.5 * mouthScale)); em.setValue('ih', clamp(m[1] * 1.2)); em.setValue('ou', clamp(m[2] * 1.4));
    em.setValue('ee', clamp(m[3] * 1.2 * mouthScale)); em.setValue('oh', clamp(m[4] * 1.4));
    em.setValue('happy', happy); em.setValue('surprised', sur * (1 - st.speak * 0.4)); em.setValue('relaxed', rel * 0.7); em.setValue('sad', sad * 0.5);
    const bl = blinkAt(h.seed * 10, t);
    em.setValue('blink', happy > 0.4 ? 0 : bl);
    h.vrm.update(dt);
  }
  // overlays
  overlays(t, cur, shot);
  renderer.render(scene, camera);
};

function overlays(t, cur, shot) {
  const { tl } = S;
  // subtitles
  let sub = '', who = '';
  for (const l of tl.lines) {
    for (const [a, b, c] of l.subs) if (t >= a - 0.05 && t < b + 0.25) { sub = c; who = l.spk; }
  }
  const sEl = $('sub');
  if (sub) { sEl.style.opacity = 1; sEl.innerHTML = `<span class="who ${who}">${tl.hosts[who].name}</span>${sub}`; } else sEl.style.opacity = 0;
  // title + lower thirds
  const ti = $('title');
  const a = smooth((t - 0.3) / 0.6) * (1 - smooth((t - tl.intro) / 0.5));
  ti.style.opacity = a; ti.style.transform = `translateY(${(1 - a) * 20}px)`;
  const lt = $('names');
  const b = smooth((t - tl.intro - 0.5) / 0.5) * (1 - smooth((t - tl.intro - 6) / 0.5));
  lt.style.opacity = b;
  // cards: shown while a carded line (and its follow-ups) is current, until the next card or 9 s
  let card = null, cs = 0;
  for (const l of tl.lines) if (l.card && t >= l.start - 0.1) { card = l.card; cs = l.start; }
  const ce = cs + 9.5;
  const cEl = $('card');
  if (card && t < ce) {
    if (S.cardShown !== card) { cEl.innerHTML = CARDS[card](tl); S.cardShown = card; }
    const k = smooth((t - cs + 0.1) / 0.45) * (1 - smooth((t - ce + 0.5) / 0.5));
    const right = shot.kind === 'cardA' || shot.kind === 'A' || (cur && cur.spk === 'A');
    cEl.className = 'card ' + (right ? 'right' : 'left');
    cEl.style.opacity = k; cEl.style.transform = `translateX(${(1 - k) * (right ? 40 : -40)}px)`;
  } else cEl.style.opacity = 0;
  // outro
  const o = $('outro');
  o.style.opacity = smooth((t - (tl.duration - 2.4)) / 0.6);
}
