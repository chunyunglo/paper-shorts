// "Behavior Decoded Tonight": a late-night talk show set with two VRM hosts, driven by a
// precomputed timeline. window.setup(timeline) loads everything; window.renderAt(t) draws time t.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const W = 1920, H = 1080;
const NAVY = 0x1d2a5c, CORAL = 0xff6b4a, CREAM = 0xf6efe3;

// ---------- deterministic noise ----------
function hash(n) { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); }
function noise1(x) { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return (hash(i) * (1 - u) + hash(i + 1) * u) * 2 - 1; }
function fbm(x, seed) { return noise1(x + seed * 17.3) * 0.6 + noise1(x * 2.1 + seed * 5.1) * 0.3 + noise1(x * 4.3 + seed) * 0.1; }
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };
const lerp = (a, b, k) => a + (b - a) * k;
const V = (x, y, z) => new THREE.Vector3(x, y, z);

// ---------- textures ----------
function canvasTex(w, h, draw) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
function woodTex(base, planks = 8, w = 1024, h = 1024, grain = 40) {
  return canvasTex(w, h, (g) => {
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    const ph = h / planks;
    for (let p = 0; p < planks; p++) {
      const shade = (hash(p * 3.1) - 0.5) * 30;
      g.fillStyle = `rgba(${shade > 0 ? 255 : 0},${shade > 0 ? 220 : 0},${shade > 0 ? 180 : 0},${Math.abs(shade) / 255})`;
      g.fillRect(0, p * ph, w, ph);
      for (let k = 0; k < grain; k++) {
        const y = p * ph + hash(p * 91 + k) * ph;
        g.strokeStyle = `rgba(30,18,10,${0.05 + hash(k * 7 + p) * 0.1})`;
        g.lineWidth = 1 + hash(k + p * 13) * 2;
        g.beginPath(); g.moveTo(0, y);
        for (let x = 0; x <= w; x += 32) g.lineTo(x, y + Math.sin(x * 0.01 + k) * 3);
        g.stroke();
      }
      g.fillStyle = 'rgba(10,5,2,0.6)'; g.fillRect(0, p * ph, w, 2);
      g.fillRect(hash(p * 5.7) * w, p * ph, 2, ph);
    }
  });
}
function fabricTex(base) {
  return canvasTex(256, 256, (g, w, h) => {
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 4000; i++) { g.fillStyle = `rgba(${hash(i) > 0.5 ? '255,255,255' : '0,0,0'},0.05)`; g.fillRect(hash(i * 1.3) * w, hash(i * 2.7) * h, 2, 1); }
  });
}

// night skyline layer: buildings with lit windows on a transparent canvas
function skylineTex(seed, opts) {
  const { w = 4096, h = 1024, count, minH, maxH, color, lit, winScale = 1 } = opts;
  return canvasTex(w, h, (g) => {
    let x = -50;
    let i = 0;
    while (x < w) {
      const bw = 60 + hash(seed + i * 1.7) * 220;
      const bh = minH + hash(seed + i * 3.1) * (maxH - minH);
      const top = h - bh;
      g.fillStyle = color; g.fillRect(x, top, bw, bh);
      // roof details
      if (hash(seed + i * 5.3) < 0.3) { g.fillRect(x + bw * 0.4, top - 30, 6, 30); g.fillStyle = '#ff3b30'; g.fillRect(x + bw * 0.4 - 2, top - 34, 10, 6); g.fillStyle = color; }
      if (hash(seed + i * 6.1) < 0.25) g.fillRect(x + bw * 0.15, top - 18, bw * 0.7, 18);
      // windows
      const ww = 8 * winScale, wh = 12 * winScale, gx = 16 * winScale, gy = 22 * winScale;
      for (let yy = top + 14; yy < h - 10; yy += gy) {
        for (let xx = x + 10; xx < x + bw - 12; xx += gx) {
          const r = hash(seed + xx * 0.37 + yy * 1.91);
          if (r < lit) {
            const warm = hash(r * 99) < 0.75;
            g.fillStyle = warm ? `rgba(255,${200 + Math.floor(hash(r * 7) * 40)},${120 + Math.floor(hash(r * 3) * 60)},${0.55 + hash(r * 11) * 0.45})` : 'rgba(170,210,255,0.8)';
            g.fillRect(xx, yy, ww, wh);
          }
        }
      }
      x += bw + hash(seed + i * 9.9) * 20; i++;
    }
  });
}

// ---------- the set ----------
function buildSet(scene) {
  const std = (o) => new THREE.MeshStandardMaterial(o);
  const add = (m, x, y, z, shadow = true) => { m.position.set(x, y, z); if (shadow) { m.castShadow = true; m.receiveShadow = true; } scene.add(m); return m; };

  // stage floor: dark glossy wood, plus a round rug under the guest chair
  const floorTex = woodTex('#2a1d16', 12, 1024, 1024, 30); floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping; floorTex.repeat.set(4, 4);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), std({ map: floorTex, roughness: 0.28, metalness: 0.15 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const rug = new THREE.Mesh(new THREE.CircleGeometry(1.5, 64), std({ map: fabricTex('#3b2440'), roughness: 1 }));
  rug.rotation.x = -Math.PI / 2; rug.position.set(-0.6, 0.004, 0.0); rug.receiveShadow = true; scene.add(rug);
  const rugRing = new THREE.Mesh(new THREE.RingGeometry(1.38, 1.45, 64), std({ color: 0xd9a441, roughness: 0.8 }));
  rugRing.rotation.x = -Math.PI / 2; rugRing.position.set(-0.6, 0.006, 0.0); scene.add(rugRing);

  // city at night behind a big window
  const sky = new THREE.Mesh(new THREE.PlaneGeometry(30, 12), new THREE.MeshBasicMaterial({
    map: canvasTex(1024, 512, (g, w, h) => {
      const gr = g.createLinearGradient(0, 0, 0, h);
      gr.addColorStop(0, '#05081c'); gr.addColorStop(0.55, '#121b48'); gr.addColorStop(0.85, '#3a2a5c'); gr.addColorStop(1, '#6b3a52');
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      for (let i = 0; i < 260; i++) { g.fillStyle = `rgba(255,255,255,${hash(i * 3) * 0.7})`; g.fillRect(hash(i) * w, hash(i * 2) * h * 0.6, 1.2, 1.2); }
      const mg = g.createRadialGradient(780, 110, 4, 780, 110, 70); mg.addColorStop(0, 'rgba(255,248,230,1)'); mg.addColorStop(0.25, 'rgba(255,240,210,0.9)'); mg.addColorStop(0.3, 'rgba(255,230,200,0.25)'); mg.addColorStop(1, 'rgba(255,230,200,0)');
      g.fillStyle = mg; g.fillRect(680, 10, 200, 200);
    }), toneMapped: false, fog: false }));
  sky.position.set(0, 4.2, -9); scene.add(sky);
  const layers = [
    { z: -8.2, y: 1.15, w: 26, h: 3.2, t: skylineTex(11, { count: 60, minH: 200, maxH: 520, color: '#0d1230', lit: 0.18, winScale: 0.6 }) },
    { z: -6.8, y: 0.95, w: 20, h: 3.6, t: skylineTex(37, { count: 40, minH: 260, maxH: 760, color: '#0a0e26', lit: 0.26, winScale: 0.85 }) },
    { z: -5.4, y: 0.7, w: 15, h: 3.8, t: skylineTex(71, { count: 30, minH: 300, maxH: 900, color: '#070a1c', lit: 0.3, winScale: 1.1 }) },
  ];
  for (const L of layers) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(L.w, L.h), new THREE.MeshBasicMaterial({ map: L.t, transparent: true, toneMapped: false, fog: false }));
    m.position.set(0, L.y + L.h / 2 - 0.4, L.z); scene.add(m);
  }
  // bridge with a string of lights across the water line
  const bridgeLights = new THREE.Group();
  for (let i = 0; i < 70; i++) {
    const x = -7 + i * 0.2, y = 1.0 + Math.cos((i - 35) / 35 * Math.PI) * 0.12;
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.018, 6, 4), new THREE.MeshBasicMaterial({ color: i % 2 ? 0xffe7a8 : 0xfff6dc, toneMapped: false, fog: false }));
    b.position.set(x, y, -6.0); bridgeLights.add(b);
  }
  scene.add(bridgeLights);

  // back wall with the window opening (wall pieces around a 7.2 x 2.9 m hole)
  const wallMat = std({ color: 0x1b2347, roughness: 0.85 });
  const wallZ = -2.6;
  add(new THREE.Mesh(new THREE.BoxGeometry(16, 0.5, 0.2), wallMat), 0, 0.25, wallZ);         // sill
  add(new THREE.Mesh(new THREE.BoxGeometry(16, 1.6, 0.2), wallMat), 0, 4.2, wallZ);          // header
  for (const s of [-1, 1]) add(new THREE.Mesh(new THREE.BoxGeometry(4.4, 4.2, 0.2), wallMat), s * 5.8, 2.1, wallZ);
  // window mullions
  const mull = std({ color: 0x0b0d14, roughness: 0.4, metalness: 0.6 });
  for (let i = 0; i <= 6; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.06, 2.95, 0.08), mull), -3.6 + i * 1.2, 1.97, wallZ + 0.02, false);
  add(new THREE.Mesh(new THREE.BoxGeometry(7.3, 0.06, 0.08), mull), 0, 2.6, wallZ + 0.02, false);
  // faint glass reflection
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(7.2, 2.95), new THREE.MeshBasicMaterial({ color: 0x8fa8ff, transparent: true, opacity: 0.05 }));
  glass.position.set(0, 1.97, wallZ); scene.add(glass);
  // side wings: wood slat panels with LED strips
  const slat = std({ map: woodTex('#8a5a3a', 1, 256, 256, 12), roughness: 0.5 });
  for (const s of [-1, 1]) {
    for (let i = 0; i < 16; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.06, 3.6, 0.06), slat), s * (3.75 + i * 0.1), 2.1, wallZ + 0.15);
    const led = new THREE.Mesh(new THREE.BoxGeometry(0.03, 3.6, 0.03), new THREE.MeshBasicMaterial({ color: s < 0 ? 0x5d7bff : CORAL, toneMapped: false }));
    led.position.set(s * 3.68, 2.1, wallZ + 0.2); scene.add(led);
  }
  // neon logo on the right wing
  const neon = canvasTex(1024, 512, (g, w, h) => {
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.shadowColor = '#ff6b4a'; g.shadowBlur = 40; g.fillStyle = '#ffd7c8';
    g.font = '900 120px "Noto Sans", sans-serif'; g.fillText('BEHAVIOR', w / 2, 150); g.fillText('DECODED', w / 2, 280);
    g.shadowColor = '#7ea2ff'; g.fillStyle = '#e4ebff'; g.font = 'italic 700 96px "Noto Serif", serif'; g.fillText('Tonight', w / 2, 410);
  });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.75), new THREE.MeshBasicMaterial({ map: neon, transparent: true, toneMapped: false }));
  sign.position.set(4.4, 2.75, wallZ + 0.25); scene.add(sign);
  const signGlow = new THREE.PointLight(0xff7a5c, 2.0, 3, 2); signGlow.position.set(4.4, 2.6, wallZ + 0.8); scene.add(signGlow);

  // lighting truss with can lights and soft beams
  const truss = std({ color: 0x2b2b30, metalness: 0.8, roughness: 0.35 });
  for (const z of [-1.2, 1.6]) {
    const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 9, 10), truss); bar.rotation.z = Math.PI / 2; add(bar, 0, 3.9, z, false);
    for (let i = 0; i < 7; i++) {
      const x = -3 + i;
      const can = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, 0.26, 16), std({ color: 0x111114, metalness: 0.6, roughness: 0.4 }));
      can.position.set(x, 3.72, z); can.rotation.x = z < 0 ? 0.35 : -0.45; scene.add(can);
      const lens = new THREE.Mesh(new THREE.CircleGeometry(0.08, 16), new THREE.MeshBasicMaterial({ color: i % 3 === 1 ? 0xffd1b8 : 0xfff3e0, toneMapped: false }));
      lens.position.set(x, 3.585, z + (z < 0 ? 0.045 : -0.06)); lens.rotation.x = Math.PI / 2 + (z < 0 ? 0.35 : -0.45); scene.add(lens);
    }
  }
  const beamMat = new THREE.MeshBasicMaterial({ color: 0xffe2c4, transparent: true, opacity: 0.022, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
  for (const [x, z, rx] of [[-2.5, -1.2, 0.35], [2.5, -1.2, 0.35]]) {
    const beam = new THREE.Mesh(new THREE.ConeGeometry(0.9, 3.6, 32, 1, true), beamMat);
    beam.position.set(x, 3.6 - 1.8, z + (rx > 0 ? 0.62 : -0.8)); beam.rotation.x = rx; scene.add(beam);
  }

  // host desk: wooden top, curved navy front with coral LED edge
  const deskX = 0.62, deskZ = -0.2;
  const top = new THREE.Mesh(new RoundedBoxGeometry(1.7, 0.06, 0.8, 4, 0.025), std({ map: woodTex('#9b6a43', 3, 1024, 512, 50), roughness: 0.35 }));
  add(top, deskX, 0.77, deskZ);
  const frontGeo = new THREE.CylinderGeometry(1.6, 1.6, 0.72, 48, 1, true, -0.55, 1.1);
  const front = new THREE.Mesh(frontGeo, std({ color: NAVY, roughness: 0.45, metalness: 0.2, side: THREE.DoubleSide }));
  add(front, deskX, 0.38, deskZ - 1.17);
  for (const y of [0.05, 0.71]) {
    const strip = new THREE.Mesh(new THREE.TorusGeometry(1.61, 0.008, 6, 64, 1.1), new THREE.MeshBasicMaterial({ color: CORAL, toneMapped: false }));
    strip.rotation.x = Math.PI / 2; strip.rotation.z = Math.PI / 2 - 0.55 - Math.PI; strip.position.set(deskX, y, deskZ - 1.17); scene.add(strip);
  }
  const logo = canvasTex(1024, 256, (g, w, h) => {
    g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = '#f6efe3';
    g.font = '900 96px "Noto Sans", sans-serif'; g.fillText('BEHAVIOR DECODED', w / 2, h / 2 - 20);
    g.fillStyle = '#ff6b4a'; g.fillRect(w / 2 - 160, h / 2 + 50, 320, 10);
  });
  const deskLogo = new THREE.Mesh(new THREE.PlaneGeometry(0.85, 0.21), new THREE.MeshBasicMaterial({ map: logo, transparent: true }));
  deskLogo.position.set(deskX, 0.42, deskZ - 1.17 + 1.615); scene.add(deskLogo);

  // desk props
  const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, 0.11, 24), std({ map: canvasTex(256, 128, (g, w, h) => { g.fillStyle = '#1d2a5c'; g.fillRect(0, 0, w, h); g.fillStyle = '#ff6b4a'; g.font = '900 44px "Noto Sans"'; g.fillText('BD', 100, 80); }), roughness: 0.3 }));
  add(mug, deskX + 0.6, 0.855, deskZ + 0.05);
  const handle = new THREE.Mesh(new THREE.TorusGeometry(0.03, 0.008, 8, 16), std({ color: NAVY, roughness: 0.3 })); handle.position.set(deskX + 0.65, 0.86, deskZ + 0.05); scene.add(handle);
  // cue cards
  const cards = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.012, 0.2), std({ color: 0x8fb3ff, roughness: 0.8 }));
  cards.rotation.y = 0.2; add(cards, deskX - 0.05, 0.806, deskZ + 0.22);
  // pen cup
  const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.1, 20), std({ color: 0x222226, metalness: 0.7, roughness: 0.3 })); add(cup, deskX + 0.45, 0.85, deskZ - 0.2);
  for (let i = 0; i < 4; i++) { const pen = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.15), std({ color: [CORAL, 0xffffff, NAVY, 0xd9a441][i] })); pen.position.set(deskX + 0.45 + (i - 1.5) * 0.012, 0.9, deskZ - 0.2); pen.rotation.z = (i - 1.5) * 0.12; scene.add(pen); }
  // small globe
  const globe = new THREE.Mesh(new THREE.SphereGeometry(0.07, 32, 16), std({ map: canvasTex(256, 128, (g, w, h) => { g.fillStyle = '#2d5d8a'; g.fillRect(0, 0, w, h); g.fillStyle = '#d9c48a'; for (let i = 0; i < 26; i++) { g.beginPath(); g.ellipse(hash(i) * w, 20 + hash(i * 3) * 90, 8 + hash(i * 5) * 22, 5 + hash(i * 7) * 14, 0, 0, 7); g.fill(); } }), roughness: 0.4 }));
  add(globe, deskX - 0.65, 0.92, deskZ - 0.22);
  const gstand = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, 0.08, 16), std({ color: 0xb08d57, metalness: 0.8, roughness: 0.3 })); add(gstand, deskX - 0.65, 0.84, deskZ - 0.22);
  // classic chrome desk microphone
  const chrome = std({ color: 0xdddde5, metalness: 1, roughness: 0.15 });
  const micG = new THREE.Group();
  micG.add(Object.assign(new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.015, 32), chrome)));
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.16), chrome); stem.position.y = 0.08; micG.add(stem);
  const capsule = new THREE.Mesh(new THREE.CapsuleGeometry(0.028, 0.05, 8, 24), chrome); capsule.position.y = 0.19; capsule.rotation.x = 0.4; micG.add(capsule);
  const grille = new THREE.Mesh(new THREE.CylinderGeometry(0.029, 0.029, 0.04, 24, 1, true), std({ color: 0x333338, metalness: 0.6, roughness: 0.6, wireframe: false }));
  grille.position.y = 0.2; grille.rotation.x = 0.4; micG.add(grille);
  micG.position.set(deskX - 0.28, 0.8, deskZ + 0.18); micG.rotation.y = 0.7; micG.traverse((o) => { o.castShadow = true; }); scene.add(micG);

  // guest armchair (velvet, coral) and side table with a lamp
  const velvet = std({ map: fabricTex('#b8473a'), roughness: 0.9 });
  const chair = new THREE.Group();
  const seat = new THREE.Mesh(new RoundedBoxGeometry(0.8, 0.16, 0.7, 4, 0.06), velvet); seat.position.y = 0.42; chair.add(seat);
  const base = new THREE.Mesh(new RoundedBoxGeometry(0.82, 0.3, 0.72, 3, 0.04), velvet); base.position.y = 0.2; chair.add(base);
  const back = new THREE.Mesh(new RoundedBoxGeometry(0.82, 0.62, 0.16, 4, 0.07), velvet); back.position.set(0, 0.75, -0.3); back.rotation.x = -0.12; chair.add(back);
  for (const s of [-1, 1]) { const arm = new THREE.Mesh(new RoundedBoxGeometry(0.14, 0.26, 0.7, 4, 0.06), velvet); arm.position.set(s * 0.37, 0.55, 0); chair.add(arm); }
  for (const s of [-1, 1]) for (const t of [-1, 1]) { const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.015, 0.06), std({ color: 0xb08d57, metalness: 0.8, roughness: 0.3 })); leg.position.set(s * 0.35, 0.03, t * 0.3); chair.add(leg); }
  chair.traverse((o) => { o.castShadow = true; o.receiveShadow = true; });
  scene.add(chair);
  const table = new THREE.Group();
  const tt = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.03, 32), std({ map: woodTex('#5a3b28', 2, 256, 256, 10), roughness: 0.4 })); tt.position.y = 0.55; table.add(tt);
  const tl = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.04, 0.55, 16), std({ color: 0xb08d57, metalness: 0.8, roughness: 0.3 })); tl.position.y = 0.275; table.add(tl);
  const lampBase = new THREE.Mesh(new THREE.SphereGeometry(0.07, 24, 16), std({ color: 0xe8e2d5, roughness: 0.3 })); lampBase.position.y = 0.62; table.add(lampBase);
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.13, 0.14, 32, 1, true), std({ color: 0xffe2b8, emissive: 0xffb36b, emissiveIntensity: 1.2, side: THREE.DoubleSide })); shade.position.y = 0.78; table.add(shade);
  const plantPot = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.04, 0.08, 16), std({ color: CORAL })); plantPot.position.set(0.12, 0.6, 0.08); table.add(plantPot);
  table.traverse((o) => { o.castShadow = true; });
  table.position.set(-1.55, 0, -0.45); scene.add(table);
  const lampLight = new THREE.PointLight(0xffb070, 0.35, 2.5, 2); lampLight.position.set(-1.55, 0.85, -0.4); scene.add(lampLight);

  // tall plants framing the set
  const leafMat = std({ color: 0x2f5a3c, roughness: 0.6, side: THREE.DoubleSide });
  for (const [px, pz] of [[-3.0, -1.6], [3.2, -1.7]]) {
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.18, 0.5, 32), std({ color: 0x1b1b1f, roughness: 0.5 })); add(pot, px, 0.25, pz);
    for (let k = 0; k < 34; k++) {
      const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 8), leafMat); leaf.scale.set(0.3, 1.3, 0.06);
      const a = k * 2.4, h = 0.7 + hash(k + px) * 1.1, rad = 0.05 + hash(k * 3 + px) * 0.25;
      leaf.position.set(px + Math.cos(a) * rad, h, pz + Math.sin(a) * rad); leaf.rotation.set(Math.sin(a) * 0.7, a, Math.cos(a) * 0.7);
      leaf.castShadow = true; scene.add(leaf);
    }
  }
  return { chair, deskX, deskZ };
}

// ---------- hosts ----------
const loader = new GLTFLoader();
loader.register((p) => new VRMLoaderPlugin(p));
const bone = (vrm, n) => vrm.humanoid.getNormalizedBoneNode(n);

// our own characters export plain PBR materials; give hair cut-out alpha and skin a little warmth
function tuneMaterial(m, o) {
  const n = m.name || '';
  if (n.startsWith('Hair') && n !== 'HairCap') { m.alphaTest = 0.3; m.alphaToCoverage = true; m.transparent = false; m.depthWrite = true; m.side = THREE.DoubleSide; o.castShadow = false; }
  if (n === 'Lashes') { m.side = THREE.DoubleSide; }
  if (window.DEBUG && window.DEBUG.hide && window.DEBUG.hide.includes(o.name)) o.visible = false;
  if (window.DEBUG && window.DEBUG.hairopaque && n.startsWith('Hair') && n !== 'HairCap') { m.alphaTest = 0; m.alphaToCoverage = false; m.map = null; m.color = new THREE.Color(1, 0, 0); }
  if (n === 'Skin' && window.DEBUG && window.DEBUG.skinflat) { m.map = null; }
  if (n === 'Skin') { m.emissive = new THREE.Color(0.22, 0.09, 0.06); m.emissiveMap = m.map; m.emissiveIntensity = 0.35; m.roughness = 0.55; }
  if (n === 'Eye') { m.roughness = 0.08; m.emissive = new THREE.Color(1, 1, 1); m.emissiveMap = m.map; m.emissiveIntensity = 0.08; }
  if (n === 'HairCap') { m.roughness = 0.9; }
  if (window.DEBUG && window.DEBUG.mouthcol && (n === 'Teeth' || n === 'Tongue')) { m.color = new THREE.Color(n === 'Teeth' ? 0x00ff00 : 0x0000ff); m.map = null; }
}

// hair: anisotropic highlight running along the strands (UV v), strand texture doubling as a bump map
function hairMaterial(m) {
  const h = new THREE.MeshPhysicalMaterial({
    name: m.name, map: m.map, color: new THREE.Color(1.2, 1.15, 1.1), roughness: 0.68, metalness: 0, specularIntensity: 0.45,
    bumpMap: m.map, bumpScale: 2.5, anisotropy: 0.4, anisotropyRotation: Math.PI / 2,
    sheen: 0.2, sheenRoughness: 0.5, sheenColor: new THREE.Color(0.3, 0.22, 0.16), alphaToCoverage: true,
    alphaTest: m.alphaTest, side: THREE.DoubleSide,
  });
  return h;
}

// animated look: cel shading in three soft bands, and an ink outline drawn as an inflated back-face shell
// that shares the mesh's skeleton and expression morphs
const TOON = !!(window.DEBUG && window.DEBUG.toon);
let toonRamp = null;
function toonify(o) {
  if (!toonRamp) {
    toonRamp = new THREE.DataTexture(new Uint8Array([120, 120, 200, 200, 255, 255]), 6, 1, THREE.RedFormat);
    toonRamp.needsUpdate = true; toonRamp.minFilter = toonRamp.magFilter = THREE.LinearFilter;
  }
  const om = o.material, n = om.name || '';
  const hair = n.startsWith('Hair');
  const m = new THREE.MeshToonMaterial({ name: n, map: om.map, color: om.color, gradientMap: toonRamp,
    transparent: false, alphaTest: om.alphaTest, alphaToCoverage: om.alphaToCoverage, side: om.side });
  if (n === 'Skin') { m.emissive = new THREE.Color(0.16, 0.07, 0.05); m.emissiveMap = om.map; m.emissiveIntensity = 0.5; }
  if (n === 'Eye') { m.emissive = new THREE.Color(1, 1, 1); m.emissiveMap = om.map; m.emissiveIntensity = 0.35; }
  if (hair) m.color = new THREE.Color(1.25, 1.2, 1.15);
  if (window.DEBUG && window.DEBUG.matcol) { m.map = null; m.emissiveMap = null; m.emissive = new THREE.Color(0, 0, 0); m.color = new THREE.Color({ Skin: 0xffcc99, Eye: 0x3333ff, Lashes: 0xff00ff, Teeth: 0x00ff00, Tongue: 0xff0000 }[n] || 0x00ffff); }
  o.material = m;
  const ink = { Skin: 0.0008, Eye: 0.0007, Lashes: 0, Teeth: 0, Tongue: 0, HairCap: 0 }[n];
  const w = ink === undefined ? 0.0016 : ink;
  if (!w || (hair && n !== 'HairBobMatte' && n !== 'HairBob')) return;
  const om2 = new THREE.MeshBasicMaterial({ color: n === 'Skin' ? 0x3a2219 : n === 'Eye' ? 0x1a0e0a : 0x111018, side: THREE.BackSide });
  om2.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader.replace('#include <skinning_vertex>',
      `#include <skinning_vertex>\n#ifdef USE_SKINNING\n  transformed += normalize(objectNormal) * ${w.toFixed(5)};\n#else\n  transformed += normalize(normal) * ${w.toFixed(5)};\n#endif`);
  };
  let shell;
  if (o.isSkinnedMesh) {
    shell = new THREE.SkinnedMesh(o.geometry, om2);
    shell.bind(o.skeleton, o.bindMatrix);
    o.parent.add(shell); shell.position.copy(o.position); shell.quaternion.copy(o.quaternion); shell.scale.copy(o.scale);
  } else {
    shell = new THREE.Mesh(o.geometry, om2); o.add(shell);
  }
  shell.userData.ink = true;
  shell.morphTargetInfluences = o.morphTargetInfluences; shell.morphTargetDictionary = o.morphTargetDictionary;
  shell.frustumCulled = false; shell.castShadow = false; shell.receiveShadow = false;
}

// swap a model's clothes for another VRoid model's (e.g. a skirt for trousers): VRoid models share bone names,
// so the donor's meshes are rebound to the recipient's skeleton, keeping the donor's bind pose
const outfitSlot = (o) => ((([].concat(o.material)[0] || {}).name || '').match(/_(Bottoms|Shoes|Tops)_/) || [])[1];
async function swapOutfit(scene, url, slots) {
  const donor = (await loader.loadAsync(url)).scene;
  const bones = {}; scene.traverse((o) => { if (o.isBone) bones[o.name] = o; });
  const drop = []; scene.traverse((o) => { if (o.isSkinnedMesh && slots.includes(outfitSlot(o))) drop.push(o); });
  const parent = drop[0].parent;
  drop.forEach((o) => o.removeFromParent());
  donor.traverse((o) => {
    if (!o.isSkinnedMesh || !slots.includes(outfitSlot(o))) return;
    const g = o.geometry.clone(), pos = g.attributes.position, nrm = g.attributes.normal;
    for (let i = 0; i < pos.count; i++) pos.setXYZ(i, pos.getX(i) + nrm.getX(i) * 0.006, pos.getY(i) + nrm.getY(i) * 0.006, pos.getZ(i) + nrm.getZ(i) * 0.006);
    const m = new THREE.SkinnedMesh(g, o.material);
    m.name = o.name; parent.add(m);
    m.bind(new THREE.Skeleton(o.skeleton.bones.map((b) => bones[b.name] || bones['J_Bip_C_Hips']), o.skeleton.boneInverses), o.bindMatrix);
  });
}

async function loadHost(url, outfit) {
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  if (outfit) await swapOutfit(gltf.scene, 'models/' + outfit.from, outfit.slots);
  const vrm0 = vrm.meta && vrm.meta.metaVersion === '0';
  if (vrm0) VRMUtils.rotateVRM0(vrm);
  vrm.scene.traverse((o) => {
    o.frustumCulled = false;
    if (!o.isMesh || o.userData.ink) return;
    o.castShadow = true; o.receiveShadow = true;
    for (const m of [].concat(o.material)) tuneMaterial(m, o);
    if (window.DEBUG && window.DEBUG.normals && o.material.name === 'Skin') o.material = new THREE.MeshNormalMaterial();
    if (TOON && !Array.isArray(o.material)) toonify(o);
    if (!TOON && !Array.isArray(o.material) && o.material.name.startsWith('Hair') && o.material.name !== 'HairCap' && o.material.name !== 'HairBobMatte') o.material = hairMaterial(o.material);
  });
  const root = new THREE.Group(); root.add(vrm.scene);
  return { vrm, root, flip: vrm0 ? -1 : 1 };
}

// seated pose plus layered animation; targets are in the host root frame (+Z forward, +X = host's left)
// right leg over left: thigh lifted and pulled across, shin angled back toward the chair, foot off the floor
const CROSS = { lu: [-1.45, 0.1, 0.05], ll: [1.45, 0, 0], ru: [-1.8, -0.2, 0.35], rl: [1.7, 0, -0.15], rf: [0.3, 0, 0] };
function applyPose(h, t, st) {
  const v = h.vrm, f = h.flip;
  const set = (n, x, y, z) => { const b = bone(v, n); if (b) b.rotation.set(x * f, y, z * f); };
  const sp = st.speak, gs = st.gesture, seed = h.seed;
  set('leftUpperLeg', -1.45, 0.1, 0.05); set('rightUpperLeg', -1.45, -0.1, -0.05);
  set('leftLowerLeg', 1.45, 0, 0); set('rightLowerLeg', 1.45, 0, 0);
  if (h.crossLegs) {
    const c = (window.DEBUG && window.DEBUG.cross) || CROSS;
    set('leftUpperLeg', ...c.lu); set('leftLowerLeg', ...c.ll); set('rightUpperLeg', ...c.ru); set('rightLowerLeg', ...c.rl); set('rightFoot', ...c.rf);
  }
  set('leftFoot', -0.1, 0, 0); if (!h.crossLegs) set('rightFoot', -0.1, 0, 0);
  const breath = Math.sin(t * 1.6 + seed) * 0.5 + 0.5;
  const sway = fbm(t * 0.35, seed) * 0.05 + fbm(t * 1.2, seed + 3) * 0.05 * sp;
  // laughing: head snaps back on the burst, then the body folds forward and pumps with each "ha"
  const laugh = st.laugh || 0, lt = st.laughT || 0, pulse = st.laughPulse || 0;
  const burst = laugh * Math.exp(-lt / 0.55) * (1 - Math.exp(-lt / 0.07));
  const fold = laugh * (1 - Math.exp(-lt / 0.5)) * (0.7 + 0.3 * hash(Math.floor(st.laughId || 0)));
  const pump = laugh * pulse * (0.55 + 0.45 * Math.exp(-lt / 1.4));
  const beat = st.beat || 0;
  set('hips', 0, 0, 0);
  set('spine', h.lean0 + breath * 0.015 + st.lean + fold * 0.13 + pump * 0.035 - burst * 0.05, sway * 0.6 + st.turn * 0.35 + fold * st.laughSide * 0.08, fbm(t * 0.3, seed + 9) * 0.03 + fold * st.laughSide * 0.05);
  set('chest', 0.04 + breath * 0.02 + pump * 0.045 + beat * 0.012, st.turn * 0.25, sway * 0.4);
  if (bone(v, 'upperChest')) set('upperChest', 0.02 + pump * 0.02, st.turn * 0.1, 0);
  // speech: small idle drift plus a nod on each stressed syllable
  const nod = fbm(t * 1.1, seed + 11) * 0.035 * sp + beat * 0.11 + st.nod;
  const tilt = fbm(t * 0.5, seed + 21) * 0.08 + st.tilt + fold * st.laughSide * 0.06;
  set('neck', 0.04 + nod * 0.4 - burst * 0.25 + fold * 0.05, st.turn * 0.25, tilt * 0.4);
  set('head', -0.03 + nod * 0.6 + fbm(t * 0.4, seed + 31) * 0.04 - burst * 0.3 + fold * 0.08 - pump * 0.04,
      st.turn * 0.4 + fbm(t * 0.3, seed + 41) * 0.08 + fbm(t * 0.9, seed + 43) * 0.04 * sp, tilt * 0.6);

  const R = h.root; R.updateMatrixWorld(true);
  const shoulderY = h.shoulderLocalY;
  const near = h.nearArm, far = near === 'left' ? 'right' : 'left';
  const k = (side) => (side === 'left' ? 1 : -1);
  const wob = (o, fr = 1.3) => fbm(t * fr, seed + o);
  const laughHand = st.laughHand || 0;   // 0 none, 1 hand to chest, 2 pat the desk / knee
  for (const side of ['left', 'right']) {
    const g = side === near ? gs.main : gs.both;
    const lift = side === near ? gs.lift || 0 : (gs.lift2 || 0);
    let rest;
    if (h.role === 'desk') rest = V(k(side) * 0.15, 0.8 - R.position.y + 0.065, h.L1 * 0.45 + h.L2 * 0.9 + (side === near ? 0.02 : 0));
    else rest = V(k(side) * (side === near ? 0.05 : 0.09), h.lapY + 0.05, h.lapZ + (side === near ? 0.03 : 0));
    const up = V(k(side) * (0.2 + wob(51 + k(side)) * 0.07), shoulderY - h.L1 * 0.55 + wob(61 + k(side), 1.7) * 0.08, h.L1 * 0.35 + h.L2 * 0.8 + wob(71 + k(side)) * 0.05);
    // phrase gestures: a softer, lower version of the full gesture
    const p = rest.clone().lerp(up, Math.max(g, lift * 0.55));
    // beats: the hand strokes down a little on stressed syllables while it is up
    const handUp = Math.max(g, lift);
    p.y -= beat * 0.035 * handUp; p.z += beat * 0.015 * handUp;
    p.x += k(side) * wob(81 + k(side), 0.6) * 0.04 * handUp;
    if (laugh > 0.05 && side === near) {
      if (laughHand === 1) p.lerp(V(k(side) * 0.04, shoulderY - h.L1 * 0.45, 0.13), smooth(fold * 1.6));
      else if (laughHand === 2) { p.y += pump * 0.05; p.z += fold * 0.03; }
    }
    if (h.role === 'desk') p.y = Math.max(p.y, 0.8 - R.position.y + 0.06);   // never through the desk top
    if (side === far && gs.wave > 0) p.lerp(V(k(side) * 0.32, shoulderY + 0.2, 0.22), gs.wave);
    const open = Math.max(g, side === far ? gs.wave : 0);
    set(side + 'Shoulder', 0, 0, -k(side) * (pump * 0.07 + burst * 0.04));
    const pole = R.localToWorld(h.role === 'desk' ? V(k(side) * 0.8, -0.6, -0.5) : V(k(side) * 0.35, -0.8, -0.45)).sub(R.getWorldPosition(V(0, 0, 0)));
    solveArm(v, side, R.localToWorld(p.clone()), pole);
    const kk = k(side);
    const waving = side === far ? gs.wave : 0;
    set(side + 'Hand', kk * open * 0.7, kk * (0.1 + waving * Math.sin(t * 10) * 0.5), -kk * (h.role === 'desk' ? 0.12 : 0.3));
    const curl = (h.role === 'desk' ? 0.28 : 0.45) - open * (h.role === 'desk' ? 0.22 : 0.38);
    for (const fn of ['Index', 'Middle', 'Ring', 'Little']) {
      const extra = (fn === 'Little' ? 0.12 : fn === 'Ring' ? 0.06 : 0) + wob(91 + fn.length, 0.7) * 0.05;
      for (const j of ['Proximal', 'Intermediate', 'Distal']) set(side + fn + j, 0, 0, -kk * (curl + extra));
    }
    set(side + 'ThumbMetacarpal', 0, kk * 0.3, -kk * 0.1); set(side + 'ThumbProximal', 0, kk * 0.2, 0);
  }
}

// point bone `b` so that its child lies along world direction `dir`
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
  const Wp = S.clone().add(dn.multiplyScalar(dist));
  aimBone(lo, hand, Wp.sub(E));
}

// ---------- overlays (HTML) ----------
const $ = (id) => document.getElementById(id);
const CARDS = {
  paper: (tl) => `<div class="kicker">TONIGHT'S PAPER</div><div class="ptitle">${tl.paper.title}</div>
    <div class="meta">${tl.paper.venue}</div><div class="meta">${tl.paper.authors}</div><div class="meta dim">${tl.paper.affil}</div>`,
  data: () => `<div class="kicker">THE DATA</div><div class="big">1.5 million</div><div class="sub">petitions on Change.org</div>
    <div class="row"><span class="pill">Oct 2, 2023</span> “Write with AI” button launches</div>`,
  design: () => `<div class="kicker">THE TRICK · DIFFERENCE-IN-DIFFERENCES</div>
    <div class="tl"><div class="lane"><b>US · UK · CA</b><div class="bar"><i style="left:30%"></i></div></div>
    <div class="lane"><b>Australia</b><div class="bar"><i style="left:62%"></i></div></div>
    <div class="gapnote">11 weeks later → the comparison group</div></div>`,
  text: () => `<div class="kicker">THE WRITING CHANGED</div>
    <div class="stat"><span class="num">+49%</span><span class="lbl">median length<br><small>~110 → ~164 words</small></span></div>
    <div class="stat"><span class="num">+1.5</span><span class="lbl">reading grade level</span></div>
    <div class="stat"><span class="num">+23%</span><span class="lbl">similarity between petitions</span></div>`,
  outcome: () => `<div class="kicker">THE RESULTS DIDN'T</div>
    <div class="stat"><span class="num down">−5.3</span><span class="lbl">chance of reaching 10 signatures<br><small>percentage points</small></span></div>
    <div class="stat"><span class="num dim">−2.5</span><span class="lbl">chance of a comment in 30 days<br><small>pp · not statistically significant</small></span></div>`,
  repeat: () => `<div class="kicker">SAME PERSON, BEFORE &amp; AFTER</div><div class="big">4,611</div><div class="sub">people who wrote petitions both before and after</div>
    <div class="row">With AI available: <b>longer</b>, <b class="coral">worse outcomes</b></div>`,
  why: () => `<div class="kicker">WHY? (THE AUTHORS' GUESSES, NOT PROOF)</div>
    <div class="row">① Same tool → everyone sounds the same</div><div class="row">② Longer text, read on phones</div>`,
  limits: () => `<div class="kicker">FINE PRINT</div>
    <div class="row">One platform: Change.org</div><div class="row">One rollout window in 2023</div><div class="row">Reasons are hypotheses</div>`,
  takeaway: () => `<div class="kicker">THE TAKEAWAY</div><div class="ptitle">AI changed what people wrote.<br>Not what happened next.</div>`,
};

// ---------- main ----------
let S = {};
window.setup = async (tl) => {
  const Q = window.QUALITY || { aa: true, shadow: 2048, scale: 1, bloom: true };
  const renderer = new THREE.WebGLRenderer({ canvas: $('c'), antialias: Q.aa, preserveDrawingBuffer: true });
  renderer.setSize(W, H, false); renderer.setPixelRatio(Q.scale);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = Q.shadow > 1024 ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05081c);
  scene.fog = new THREE.Fog(0x0b1030, 9, 20);
  const set = buildSet(scene);
  // soft image-based light: gives eyes their catchlights and fabric/skin some sheen
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.22;

  // lights: warm key from front-left, cool rim from behind (city), fill
  scene.add(new THREE.HemisphereLight(0xffe9d6, 0x1a2040, 0.55));
  const key = new THREE.SpotLight(0xfff0dd, 10, 14, 0.6, 0.7, 1.2); key.position.set(-0.4, 3.8, 3.6); key.target.position.set(0.3, 0.9, -0.4);
  key.castShadow = true; key.shadow.mapSize.set(Q.shadow, Q.shadow); key.shadow.bias = -0.0003; key.shadow.normalBias = 0.02; scene.add(key, key.target);
  const fill = new THREE.DirectionalLight(0xc8d4ff, 0.45); fill.position.set(3, 2, 3); scene.add(fill);
  const rim = new THREE.DirectionalLight(0x9fb4ff, 0.9); rim.position.set(0.5, 3, -4); scene.add(rim);
  const rim2 = new THREE.DirectionalLight(0xffa58a, 0.5); rim2.position.set(-3, 2.5, -3); scene.add(rim2);

  const hosts = {};
  for (const [key_, cfg] of Object.entries(tl.hosts)) {
    const h = await loadHost('models/' + cfg.model, cfg.outfit);
    Object.assign(h, { key: key_, role: cfg.role, seed: cfg.seed || (key_ === 'A' ? 1.3 : 7.7), crossLegs: !!cfg.crossLegs, mouth: cfg.mouth ?? 1 });
    scene.add(h.root); hosts[key_] = h;
  }
  const host = Object.values(hosts).find((h) => h.role === 'desk');
  const guest = Object.values(hosts).find((h) => h.role !== 'desk');
  host.other = guest; guest.other = host;
  // placement
  const place = (h, x, z, yaw, seatTop) => {
    const v = h.vrm; v.update(0); h.root.updateMatrixWorld(true);
    const hy = bone(v, 'hips').getWorldPosition(V(0, 0, 0)).y;
    const sy = bone(v, 'leftUpperArm').getWorldPosition(V(0, 0, 0)).y;
    h.L1 = bone(v, 'leftLowerArm').position.length(); h.L2 = bone(v, 'leftHand').position.length();
    const thigh = bone(v, 'leftLowerLeg').position.length();
    const seatY = seatTop ?? (0.8 + 0.8 * h.L1 - (sy - hy));
    h.root.position.set(x, seatY - hy, z); h.root.rotation.y = yaw;
    h.shoulderLocalY = sy; h.lapY = hy + 0.08; h.lapZ = thigh * 0.75; h.lean0 = h.role === 'desk' ? 0.1 : 0.0;
  };
  place(host, set.deskX + 0.02, set.deskZ - 0.46, -0.3);
  place(guest, -0.66, 0.12, 0.62, 0.56);
  set.chair.position.set(-0.66 - Math.sin(0.62) * 0.06, 0, 0.12 - Math.cos(0.62) * 0.06); set.chair.rotation.y = 0.62;
  // the host's office chair, seat just under the hips
  {
    const mat = new THREE.MeshStandardMaterial({ color: 0x1b1b22, roughness: 0.5 });
    const c = new THREE.Group();
    c.add(new THREE.Mesh(new RoundedBoxGeometry(0.52, 0.08, 0.5, 2, 0.03), mat));
    const back = new THREE.Mesh(new RoundedBoxGeometry(0.5, 0.75, 0.08, 2, 0.04), mat); back.position.set(0, 0.45, -0.26); c.add(back);
    c.children.forEach((o) => { o.castShadow = true; });
    c.position.set(host.root.position.x, bone(host.vrm, 'hips').getWorldPosition(V(0, 0, 0)).y - 0.12, host.root.position.z - 0.06);
    c.rotation.y = -0.3; scene.add(c);
  }
  host.nearArm = 'right'; guest.nearArm = 'left';
  for (const h of Object.values(hosts)) { applyPose(h, 0, idleState()); h.vrm.update(0); h.headPos = bone(h.vrm, 'head').getWorldPosition(V(0, 0, 0)); }

  const camera = new THREE.PerspectiveCamera(32, W / H, 0.05, 60);
  let composer = null;
  if (Q.bloom) {
    composer = new EffectComposer(renderer);
    composer.setPixelRatio(Q.scale); composer.setSize(W, H);
    composer.addPass(new RenderPass(scene, camera));
    composer.addPass(new UnrealBloomPass(new THREE.Vector2(W * Q.scale / 2, H * Q.scale / 2), 0.4, 0.45, 0.97));
    composer.addPass(new OutputPass());
  }
  S = { renderer, composer, scene, camera, hosts, host, guest, tl, lastT: null, cardShown: null, beats: {} };
  for (const k of Object.keys(hosts)) S.beats[k] = findBeats(tl.mouth[k], tl.fps);
  buildShots();
  return true;
};

// stressed syllables: peaks in the rise of mouth energy, at least 0.22 s apart
function findBeats(track, fps) {
  const e = track.map((m) => (m ? m.reduce((a, b) => a + b, 0) : 0));
  const on = e.map((x, i) => { let a = 0; for (let k = 1; k <= 5; k++) a += e[Math.max(0, i - k)]; return Math.max(0, x - a / 5); });
  const sorted = on.filter((x) => x > 0).sort((a, b) => a - b);
  const thr = sorted.length ? sorted[Math.floor(sorted.length * 0.85)] : 1, top = sorted.length ? sorted[sorted.length - 1] : 1;
  const out = []; let last = -1;
  for (let i = 1; i < on.length - 1; i++) {
    if (on[i] < thr || on[i] < on[i - 1] || on[i] < on[i + 1]) continue;
    const t = i / fps;
    if (out.length && t - last < 0.22) { if (on[i] / top > out[out.length - 1].a) { out[out.length - 1] = { t, a: on[i] / top }; last = t; } continue; }
    out.push({ t, a: Math.min(1, 0.4 + 0.6 * on[i] / top) }); last = t;
  }
  return out;
}

function idleState() { return { speak: 0, lean: 0, turn: 0, nod: 0, tilt: 0, laugh: 0, laughT: 0, laughPulse: 0, laughSide: 0, laughHand: 0, laughId: 0, beat: 0, gesture: { main: 0, both: 0, wave: 0, lift: 0, lift2: 0 } }; }

// camera shots from the timeline: close-ups follow the speaker, quick exchanges and laughs go wide
function buildShots() {
  const { tl, host } = S; const shots = [];
  shots.push({ start: 0, end: tl.intro, kind: 'intro' });
  let cur = null;
  tl.lines.forEach((l, i) => {
    const dur = l.end - l.start;
    const who = l.spk === host.key ? 'host' : 'guest';
    let kind = l.card ? 'card_' + who : l.toCamera ? 'mono' : who;
    if (!l.card && dur < 1.3) kind = 'wide';
    if (!l.card && !l.toCamera && dur >= 1.3 && hash(i * 3.3) < 0.2) kind = 'two_' + who;
    const start = i === 0 ? tl.intro : Math.max(l.start - 0.12, shots[shots.length - 1].start + 0.8);
    if (cur && cur.kind === kind) { cur.end = l.end; return; }
    if (cur) cur.end = start;
    cur = { start, end: l.end, kind };
    shots.push(cur);
    if (l.laugh && l.laugh > 0.5) { cur.end = l.end + 0.3; cur = { start: l.end + 0.3, end: l.end + 1.2, kind: 'wide' }; shots.push(cur); }
  });
  cur.end = tl.duration - tl.outro;
  shots.push({ start: tl.duration - tl.outro, end: tl.duration + 1, kind: 'outro' });
  S.shots = shots;
}

function setCamera(t) {
  const { camera, host, guest } = S;
  const shot = S.shots.find((s) => t >= s.start && t < s.end) || S.shots[S.shots.length - 1];
  const u = (t - shot.start) / Math.max(0.1, shot.end - shot.start);
  const drift = (a) => fbm(t * 0.15, a) * 0.025;
  const hh = host.headPos, gh = guest.headPos;
  const mid = hh.clone().add(gh).multiplyScalar(0.5);
  let pos, look, fov = 30;
  switch (shot.kind) {
    case 'intro': { const k = smooth(u * 1.1); pos = V(lerp(-2.2, -0.15, k), lerp(3.4, 1.45, k), lerp(5.5, 3.9, k)); look = V(lerp(0, 0, k), lerp(1.8, 1.0, k), -0.6); fov = lerp(40, 34, k); break; }
    case 'outro': { const k = smooth(u); pos = V(lerp(-0.15, 0.6, k), lerp(1.45, 2.6, k), lerp(3.9, 5.6, k)); look = V(0, lerp(1.0, 1.6, k), -1); fov = 36; break; }
    case 'mono': pos = V(hh.x - 0.1 + drift(5) * 2, hh.y + 0.05, hh.z + 2.3 - u * 0.15); look = hh.clone().add(V(0, -0.2, 0)); fov = 27; break;
    case 'wide': pos = V(-0.15 + drift(1) * 4, 1.35 + drift(2), 3.8 - u * 0.15); look = mid.clone().add(V(0, -0.2, 0)); fov = 33; break;
    case 'host': case 'card_host': case 'two_host': {
      const card = shot.kind.startsWith('card'), two = shot.kind.startsWith('two');
      if (two) { pos = V(-1.7, 1.3, 1.9); look = hh.clone().add(V(-0.2, -0.2, 0)); fov = 30; break; }
      pos = V(hh.x - 0.25, hh.y + 0.04 + drift(3), hh.z + 1.95 - u * 0.1);
      look = hh.clone().add(V(card ? -0.28 : -0.05, -0.16, 0)); fov = card ? 30 : 26; break;
    }
    case 'guest': case 'card_guest': case 'two_guest': {
      const card = shot.kind.startsWith('card'), two = shot.kind.startsWith('two');
      if (two) { pos = V(1.6, 1.32, 1.8); look = gh.clone().add(V(0.25, -0.22, 0)); fov = 30; break; }
      pos = V(gh.x + 1.25, gh.y + 0.04 + drift(4), gh.z + 1.45 - u * 0.1);
      look = gh.clone().add(V(card ? 0.3 : 0.05, -0.2, 0)); fov = card ? 30 : 26; break;
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
  const track = tl.mouth[key];
  const f = Math.min(Math.floor(t * tl.fps), track.length - 1);
  const m = track[Math.max(0, f)] || [0, 0, 0, 0, 0];
  let act = 0; for (let k = 0; k < 12; k++) { const mm = track[Math.max(0, f - k)] || [0, 0, 0, 0, 0]; act += mm.reduce((a, b) => a + b, 0); }
  st.speak = Math.min(1, act / 12 * 2.5);
  st.mouth = m;
  st.emo = {};
  for (const l of tl.lines) {
    if (l.spk === key) {
      const w = smooth((t - l.start + 0.15) / 0.35) * (1 - smooth((t - l.end - 0.6) / 0.6));
      if (w <= 0) continue;
      if (l.emo) st.emo[l.emo] = Math.max(st.emo[l.emo] || 0, w * ({ surprised: 0.7, happy: 0.45 }[l.emo] || 0.6));
      if (l.gest) {
        const gw = smooth((t - l.start - 0.1) / 0.5) * (1 - smooth((t - l.end + 0.3) / 0.5));
        if (l.gest === 'both') { st.gesture.both = Math.max(st.gesture.both, gw); st.gesture.main = Math.max(st.gesture.main, gw); }
        else if (l.gest === 'wave') st.gesture.wave = Math.max(st.gesture.wave, smooth((t - l.end + 1.6) / 0.4) * (1 - smooth((t - l.end - 1.4) / 0.4)));
        else st.gesture.main = Math.max(st.gesture.main, gw * (l.gest === 'explain' ? 1 : 0.8));
      }
    } else {
      if (l.emo === 'happy') {
        const w = smooth((t - l.start - 0.3) / 0.5) * (1 - smooth((t - l.end - 0.8) / 0.5));
        st.emo.happy = Math.max(st.emo.happy || 0, w * 0.3);
      }
      if (l.back && l.back.spk === key) {
        const d = t - l.back.start; if (d > -0.1 && d < 0.9) st.nod += Math.sin(clamp(d / 0.9) * Math.PI * 2) * 0.09;
      }
      const d = t - l.end; if (d > -0.3 && d < 0.6) st.nod += Math.sin(clamp((d + 0.3) / 0.9) * Math.PI) * 0.05;
    }
  }
  // audience laughs: everybody grins; the one who did not make the joke laughs harder.
  // Each laugh gets its own onset time, rhythm ("ha" pulses ~4-5 Hz with jitter), lean side and hand.
  st.laughT = 0; st.laughPulse = 0; st.laughSide = 0; st.laughHand = 0; st.laughId = 0;
  for (const s of tl.sfx) {
    if (s.kind !== 'laugh') continue;
    const mine = s.after === key;
    const lag = mine ? 0.05 : 0.12 + hash(s.start * 7 + key.charCodeAt(0)) * 0.15;   // reacting a beat after the punchline
    const lt = t - s.start - lag;
    const w = smooth(lt / 0.12) * (1 - smooth((t - s.end + 0.3) / 0.7)) * s.gain;
    if (w <= 0) continue;
    const amt = w * (mine ? 0.45 : 1);
    if (amt <= st.laugh) continue;
    st.laugh = amt; st.laughT = Math.max(0, lt); st.laughId = s.start * 13 + key.charCodeAt(0);
    const r = hash(st.laughId);
    const rate = 4.2 + r * 1.0;
    const ph = 2 * Math.PI * (rate * st.laughT + 0.35 * fbm(st.laughT * 1.5, r * 9)) ;
    st.laughPulse = Math.pow(0.5 + 0.5 * Math.sin(ph), 2.5) * (0.6 + 0.4 * fbm(st.laughT * 3, r * 5 + 1));
    st.laughSide = (hash(st.laughId + 3) - 0.5) * 2;
    st.laughHand = mine ? 0 : (r < 0.4 ? 1 : r < 0.75 ? 2 : 0);
    st.emo.happy = Math.max(st.emo.happy || 0, amt * (mine ? 0.65 : 0.95));
  }
  // speech beats from the voice track: stressed syllables nod the head and stroke the hand
  st.beat = 0;
  const B = S.beats[key];
  for (let i = 0; i < B.length; i++) {
    const d = t - B[i].t;
    if (d < -0.25) break;
    if (d > 0.5) continue;
    st.beat += B[i].a * (Math.exp(-(((d + 0.06) / 0.11) ** 2)) - 0.35 * Math.exp(-(((d - 0.2) / 0.12) ** 2)));
  }
  // phrase gestures on longer lines without a scripted gesture: one hand comes up for part of the line
  for (const [i, l] of tl.lines.entries()) {
    if (l.spk !== key || l.gest || l.end - l.start < 2.2) continue;
    const r = hash(i * 5.7 + key.charCodeAt(0));
    if (r < 0.25) continue;
    const a = l.start + 0.3 + r * 0.6, b = l.end - 0.2;
    const w = smooth((t - a) / 0.45) * (1 - smooth((t - b) / 0.5)) * (0.55 + 0.45 * Math.max(0, fbm(t * 0.35, i)));
    if (w <= 0) continue;
    if (r > 0.8) st.gesture.lift2 = Math.max(st.gesture.lift2 || 0, w * 0.8);
    st.gesture.lift = Math.max(st.gesture.lift || 0, w);
  }
  st.lean = st.speak * 0.04;
  st.tilt = (st.emo.surprised || 0) * -0.06 + (st.emo.happy || 0) * 0.05;
  return st;
}

function blinkAt(seed, t) {
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
  const { renderer, composer, scene, camera, hosts } = S;
  const dt = S.lastT === null ? 1 / 30 : Math.max(0.0001, Math.min(0.1, t - S.lastT));
  S.lastT = t;
  const shot = setCamera(t);
  const cur = lineAt(t);
  for (const [k, h] of Object.entries(hosts)) {
    const st = hostState(k, t);
    const talking = cur && cur.spk === k;
    const closeOnMe = shot.kind === (h.role === 'desk' ? 'host' : 'guest');
    const toCam = talking && closeOnMe && hash(Math.floor(t / 2.7) + h.seed) < 0.3;
    // the host plays to the audience during the monologue and laughs
    const toAudience = h.role === 'desk' && (st.laugh > 0.4 || (cur && cur.toCamera && talking));
    const target = toCam || toAudience ? camera.position.clone() : h.other.headPos.clone().add(V(0, -0.03 - st.laugh * 0.25, 0));
    const targetTurn = toCam || toAudience ? 0.35 * (h.role === 'desk' ? 1 : -1) : 0;
    h.turn = h.turn === undefined ? targetTurn : h.turn + (targetTurn - h.turn) * Math.min(1, dt * 4);
    st.turn = h.turn;
    applyPose(h, t, st);
    if (!h.lookObj) { h.lookObj = new THREE.Object3D(); scene.add(h.lookObj); h.vrm.lookAt.target = h.lookObj; h.lookObj.position.copy(target); if (window.DEBUG && window.DEBUG.nolook) h.vrm.lookAt.autoUpdate = false; }
    h.lookObj.position.lerp(target, Math.min(1, dt * 6));
    h.lookObj.position.x += fbm(t * 3, h.seed + 99) * 0.01;
    const em = h.vrm.expressionManager;
    const m = st.mouth;
    const happy = st.emo.happy || 0, sur = st.emo.surprised || 0, rel = st.emo.relaxed || 0, sad = st.emo.sad || 0;
    const laughOpen = st.laugh * (0.18 + 0.5 * st.laughPulse) * (0.6 + 0.4 * Math.exp(-st.laughT / 1.6));
    const ms = 1 - happy * 0.3;
    const mo = h.mouth;   // VRoid mouths open very wide at full weight, showing the whole tongue
    em.setValue('aa', clamp(m[0] * 1.5 * ms + laughOpen) * mo); em.setValue('ih', clamp(m[1] * 1.2) * mo); em.setValue('ou', clamp(m[2] * 1.4) * mo);
    em.setValue('ee', clamp(m[3] * 1.2 * ms + st.laugh * 0.15) * mo); em.setValue('oh', clamp(m[4] * 1.4) * mo);
    em.setValue('happy', clamp(happy)); if (em.getExpression('surprised')) em.setValue('surprised', sur * (1 - st.speak * 0.4));
    em.setValue('relaxed', rel * 0.7); em.setValue('sad', sad * 0.5);
    const squint = clamp(st.laugh * (0.12 + 0.12 * st.laughPulse));   // eyes narrow while laughing, never shut
    em.setValue('blink', Math.max(squint, happy > 0.4 ? 0 : blinkAt(h.seed * 10, t)));
    if (window.DEBUG && window.DEBUG.expr) { for (const n of ['aa','ih','ou','ee','oh','happy','relaxed','sad','surprised','angry','blink']) if (em.getExpression(n)) em.setValue(n, window.DEBUG.expr[n] || 0); }
    h.vrm.update(dt);
  }
  overlays(t, cur, shot);
  if (composer) composer.render(); else renderer.render(scene, camera);
};

window.debugBoxes = (k) => {
  const h = S.hosts[k]; const out = {};
  h.vrm.scene.traverse((o) => { if (o.isMesh) { const b = new THREE.Box3().setFromObject(o, true); out[o.name + ':' + (o.material.name || '')] = [b.min.toArray().map((x) => +x.toFixed(3)), b.max.toArray().map((x) => +x.toFixed(3))]; } });
  out.head = bone(h.vrm, 'head').getWorldPosition(V(0, 0, 0)).toArray().map((x) => +x.toFixed(3));
  return out;
};
window.debugVis = (k) => { const r = []; S.hosts[k].vrm.scene.traverse((o) => { if (o.isMesh) r.push([o.name, o.visible, o.layers.mask, o.material.name, o.material.visible, o.material.opacity, o.geometry.attributes.position.count, o.geometry.drawRange.count]); }); return r; };
window.debugHide = (k, names) => S.hosts[k].vrm.scene.traverse((o) => { if (o.isMesh && names.includes(o.name)) o.visible = false; });
// debug: put the camera on one face and draw again
window.closeup = (k, side = 0, dy = 0.06, dist = 0.55) => {
  const { camera, hosts, composer, renderer, scene } = S;
  const h = hosts[k]; const p = bone(h.vrm, 'head').getWorldPosition(V(0, 0, 0)).add(V(0, dy, 0));
  const fwd = V(Math.sin(h.root.rotation.y + side), 0, Math.cos(h.root.rotation.y + side));
  camera.position.copy(p.clone().add(fwd.multiplyScalar(dist))); camera.fov = 30; camera.updateProjectionMatrix(); camera.lookAt(p);
  if (composer) composer.render(); else renderer.render(scene, camera);
};

function overlays(t, cur, shot) {
  const { tl, hosts } = S;
  let sub = '', who = '';
  for (const l of tl.lines) for (const [a, b, c] of l.subs) if (t >= a - 0.05 && t < b + 0.2) { sub = c; who = l.spk; }
  const sEl = $('sub');
  if (sub) { sEl.style.opacity = 1; sEl.innerHTML = `<span class="who ${who}">${tl.hosts[who].name}</span>${sub}`; } else sEl.style.opacity = 0;
  const ti = $('title');
  const a = smooth((t - 0.6) / 0.6) * (1 - smooth((t - tl.intro + 0.4) / 0.5));
  ti.style.opacity = a; ti.style.transform = `scale(${0.94 + a * 0.06})`;
  const lt = $('names');
  const first = (k) => tl.lines.find((l) => l.spk === k);
  for (const k of Object.keys(hosts)) {
    const l = first(k); const el = $('name' + k);
    const b = l ? smooth((t - l.start - 0.3) / 0.4) * (1 - smooth((t - l.start - 5) / 0.4)) : 0;
    el.style.opacity = b; el.style.transform = `translateX(${(1 - b) * -30}px)`;
  }
  let card = null, cs = 0;
  for (const l of tl.lines) if (l.card && t >= l.start - 0.1) { card = l.card; cs = l.start; }
  const ce = cs + 9.5;
  const cEl = $('card');
  if (card && t < ce) {
    if (S.cardShown !== card) { cEl.innerHTML = CARDS[card](tl); S.cardShown = card; }
    const k = smooth((t - cs + 0.1) / 0.45) * (1 - smooth((t - ce + 0.5) / 0.5));
    cEl.className = 'card ' + (shot.kind.endsWith('host') ? 'left' : 'right');
    cEl.style.opacity = k; cEl.style.transform = `translateY(${(1 - k) * 24}px)`;
  } else cEl.style.opacity = 0;
  $('outro').style.opacity = smooth((t - (tl.duration - tl.outro + 0.6)) / 0.8);
}
