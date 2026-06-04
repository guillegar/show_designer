/**
 * Show Designer · 3D Viewer
 *
 * Renderiza el rig de barras LED en 3D usando Three.js.
 * Recibe los frames RGB en tiempo real por WebSocket desde dual_app.py.
 *
 * Implementación original. Three.js (MIT) — ver CREDITS.md.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass }     from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass }      from 'three/addons/postprocessing/OutputPass.js';
import { MovingHead }      from './moving_head.js';

// ── Constantes globales ───────────────────────────────────────────
const NUM_BARS = 10;
const LEDS_PER_BAR = 93;
const BAR_WIDTH = 0.06;
const LED_HEIGHT = 0.012;   // altura visual de cada LED
const WS_URL = `ws://${location.hostname || '127.0.0.1'}:9877`;
const LAYOUT_URL = './rig_layout.json';

// ── DOM ──────────────────────────────────────────────────────────
const wsStatusEl = document.getElementById('ws-status');
const fpsEl = document.getElementById('fps');
const barInfoEl = document.getElementById('bar-info');

// ── Three.js setup ───────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color('#06080c');
// v1.9 F9: bajado de 0.045 a 0.025 — el fog atenuaba ~50% a la distancia
// de los movers (16m) y los hacía invisibles. Mantiene profundidad
// atmosférica con menos compresión visual.
scene.fog = new THREE.FogExp2(0x06080c, 0.025);  // niebla volumétrica, da profundidad

const camera = new THREE.PerspectiveCamera(
  60, window.innerWidth / window.innerHeight, 0.1, 200
);
// Ángulo elevado para que entren los 4 movers de los flancos (X=±7)
camera.position.set(0, 4.5, 16);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
document.body.appendChild(renderer.domElement);

// Bloom post-FX para hacer brillar los LEDs encendidos
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  0.85,   // strength
  0.45,   // radius
  0.10    // threshold (debajo de esto no brilla)
);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 2.0, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI / 2 - 0.05;

// Ambient + un punto de luz suave
// v1.9 F9: subido keyLight intensidad de 0.6 a 1.0 para que los cuerpos
// metálicos de los movers respondan visiblemente sin romper el look "club".
scene.add(new THREE.AmbientLight(0x222233, 1.0));
const keyLight = new THREE.DirectionalLight(0x6688aa, 1.0);
keyLight.position.set(8, 12, 6);
scene.add(keyLight);

// ── Escenario: suelo + telón de fondo ────────────────────────────
{
  // Suelo
  const floorGeom = new THREE.PlaneGeometry(80, 40);
  const floorMat = new THREE.MeshStandardMaterial({
    color: 0x0e0e14, roughness: 0.85, metalness: 0.2,
  });
  const floor = new THREE.Mesh(floorGeom, floorMat);
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);

  // Rejilla sutil
  const grid = new THREE.GridHelper(80, 80, 0x222232, 0x101018);
  grid.position.y = 0.002;
  scene.add(grid);

  // Telón de fondo (pared al fondo del escenario)
  const wallGeom = new THREE.PlaneGeometry(80, 18);
  const wallMat = new THREE.MeshStandardMaterial({
    color: 0x070710, roughness: 0.95, metalness: 0.0,
  });
  const wall = new THREE.Mesh(wallGeom, wallMat);
  wall.position.set(0, 9, -5);
  scene.add(wall);
}

// ── Sistema de barras LED ────────────────────────────────────────
/**
 * Una "barra" se modela como un grupo de cubos pequeños (1 por LED),
 * apilados verticalmente. Cada LED tiene un material emissive cuyo color
 * actualizamos cada frame desde el WebSocket.
 */
class LEDBar {
  constructor(position, rotation, length, numLeds) {
    this.group = new THREE.Group();
    this.group.position.set(...position);
    this.group.rotation.set(...rotation);

    this.numLeds = numLeds;
    this.length = length;

    // Cuerpo MUY delgado y desplazado hacia atrás para que NO oculte los LEDs.
    // Una barra WLED real es prácticamente solo una tira de LEDs.
    const bodyDepth = BAR_WIDTH * 0.4;
    const bodyGeom = new THREE.BoxGeometry(BAR_WIDTH * 0.5, length, bodyDepth);
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0x080810, roughness: 0.7, metalness: 0.3,
    });
    const body = new THREE.Mesh(bodyGeom, bodyMat);
    body.position.set(0, length / 2, -bodyDepth);   // detrás de los LEDs
    this.group.add(body);

    // LEDs como pequeños cubos emissive — visibles en frente del cuerpo
    const ledHeight = length / numLeds;
    this.ledMeshes = [];
    this.ledColors = new Float32Array(numLeds * 3);

    // LEDs un poco más anchos que el body para que sobresalgan a los lados
    const ledGeom = new THREE.BoxGeometry(BAR_WIDTH * 0.95, ledHeight * 0.95, BAR_WIDTH * 0.55);
    for (let i = 0; i < numLeds; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: 0x000000,
        emissive: 0x000000,
        emissiveIntensity: 3.5,
        roughness: 0.25,
        metalness: 0.0,
      });
      const led = new THREE.Mesh(ledGeom, mat);
      // LED 0 abajo, LED N-1 arriba; centrado en X/Z=0 (frente del body)
      led.position.set(0, ledHeight / 2 + i * ledHeight, 0);
      this.group.add(led);
      this.ledMeshes.push(led);
    }
  }

  /**
   * Actualiza los colores de la barra desde un array RGB plano
   * (length = numLeds * 3, valores 0-255, orden R G B R G B...)
   */
  setRGB(rgbArray) {
    const n = Math.min(this.numLeds, Math.floor(rgbArray.length / 3));
    for (let i = 0; i < n; i++) {
      const r = rgbArray[i * 3] / 255;
      const g = rgbArray[i * 3 + 1] / 255;
      const b = rgbArray[i * 3 + 2] / 255;
      const mat = this.ledMeshes[i].material;
      mat.emissive.setRGB(r, g, b);
      mat.color.setRGB(r * 0.3, g * 0.3, b * 0.3);
    }
  }

  setAllBlack() {
    for (let i = 0; i < this.numLeds; i++) {
      const mat = this.ledMeshes[i].material;
      mat.emissive.setRGB(0, 0, 0);
      mat.color.setRGB(0, 0, 0);
    }
  }
}

// ── Cargar layout y crear fixtures ──────────────────────────────
const bars = [];          // LEDBar
const movers = [];        // MovingHead
let layoutLoaded = false;

async function loadLayout() {
  try {
    const resp = await fetch(LAYOUT_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const layout = await resp.json();

    // Limpiar items viejos si existen
    bars.forEach(b => scene.remove(b.group));
    bars.length = 0;
    movers.forEach(m => scene.remove(m.group));
    movers.length = 0;

    // Crear fixtures según tipo
    layout.fixtures.forEach(fx => {
      if (fx.type === 'led_strip') {
        const bar = new LEDBar(fx.position, fx.rotation || [0, 0, 0],
                               fx.length || 1.0, fx.leds || LEDS_PER_BAR);
        bar.fixtureId = fx.id;
        scene.add(bar.group);
        bars.push(bar);
      } else if (fx.type === 'moving_head' || fx.type === 'wash' || fx.type === 'beam') {
        const md = fx.metadata || {};
        const angleDeg = md.beam_angle_deg || (fx.type === 'beam' ? 6 : 22);
        const mh = new MovingHead({
          color: 0xffffff,
          intensity: 0.0,          // empieza apagado, espera DMX real
          angleDeg: angleDeg,
          beamLength: fx.type === 'beam' ? 12.0 : 7.5,
          fogDensity: 0.35,
        });
        // Posicionar el grupo
        mh.group.position.set(fx.position[0], fx.position[1] || 4.0, fx.position[2]);
        mh.fixtureId = fx.id;
        // v1.7 Fase 4 — metadata para mapear DMX
        mh.maxPanDeg = md.max_pan_deg || 540;
        mh.maxTiltDeg = md.max_tilt_deg || 270;
        mh.channels = new Set(fx.channels || ['pan','tilt','dim','r','g','b']);
        scene.add(mh.group);
        movers.push(mh);
      } else if (fx.type === 'strobe') {
        const strobe = new Strobe(fx);
        scene.add(strobe.group);
        movers.push(strobe);   // tratamos como entidad DMX (lista única)
      } else if (fx.type === 'dimmer') {
        const dimmer = new Dimmer(fx);
        scene.add(dimmer.group);
        movers.push(dimmer);
      }
    });

    barInfoEl.textContent =
      `${bars.length} barras · ${movers.length} movers · ${bars[0]?.numLeds || 0} LEDs/barra`;
    layoutLoaded = true;
    console.log(`[viewer3d] Layout cargado: ${bars.length} barras, ${movers.length} movers`);

    // ── DEMO inicial — encender barras + movers ─────────────────
    // Cuando llegue un frame real del show vía WS se sobreescribirá al instante.

    // Barras: gradiente vertical de rojo (abajo) → ámbar (medio) → blanco (arriba)
    bars.forEach((bar, barIdx) => {
      const buf = new Uint8Array(bar.numLeds * 3);
      for (let led = 0; led < bar.numLeds; led++) {
        const t = led / bar.numLeds;   // 0=abajo, 1=arriba
        // Mezcla suave de tres colores
        const r = Math.round(255 * (0.30 + 0.70 * t));
        const g = Math.round(255 * (0.05 + 0.60 * t * t));
        const b = Math.round(255 * (0.00 + 0.40 * Math.pow(t, 4)));
        buf[led * 3 + 0] = r;
        buf[led * 3 + 1] = g;
        buf[led * 3 + 2] = b;
      }
      bar.setRGB(buf);
    });

    // v1.7 Fase 4 — los movers ya no tienen demo estática. El DMX real
    // llega por WS (mensaje JSON {"type":"dmx", ...}). Como pose inicial
    // antes del primer mensaje: dim=0, apuntando ligeramente hacia el centro
    // para que sea evidente dónde está cada uno.
    movers.forEach((m) => {
      if (typeof m.setColor !== 'function') return;
      m.setColor(1.0, 1.0, 1.0);
      m.setIntensity(0.0);   // apagado al inicio; el DMX lo enciende
      const isLeft = m.group.position.x < 0;
      m.setPan(isLeft ? 25 : -25);
      m.setTilt(64);
    });
  } catch (e) {
    console.error(`[viewer3d] Error cargando layout:`, e);
    barInfoEl.textContent = `[error: no se pudo cargar rig_layout.json]`;
  }
}

// ── Strobe simple — panel emisivo que parpadea ──────────────────
class Strobe {
  constructor(fx) {
    this.fixtureId = fx.id;
    this.group = new THREE.Group();
    this.group.position.set(fx.position[0], fx.position[1] || 4.0, fx.position[2]);

    const geom = new THREE.PlaneGeometry(0.6, 0.6);
    this.mat = new THREE.MeshStandardMaterial({
      color: 0x000000,
      emissive: 0xffffff,
      emissiveIntensity: 0.0,
      side: THREE.DoubleSide,
    });
    const panel = new THREE.Mesh(geom, this.mat);
    this.group.add(panel);

    // Estado DMX
    this._intensity = 0.0;
    this._speed = 0.0;     // 0..1 normalizado, en JS lo mapeamos a 0..25 Hz
    this._phase = 0.0;
    this.channels = new Set(['intensity', 'speed']);
    this.maxStrobeHz = (fx.metadata && fx.metadata.max_strobe_hz) || 25.0;
  }
  // API "tipo MovingHead" para que applyDmxState() no necesite ramas extra
  setIntensity(v) { this._intensity = Math.max(0, Math.min(1, v)); }
  setSpeed(v)     { this._speed = Math.max(0, Math.min(1, v)); }
  setColor(r, g, b) { this.mat.emissive.setRGB(r, g, b); }
  setPan(_)  {}
  setTilt(_) {}
  update(dt) {
    // Mientras speed=0 → luz continua a intensity. speed>0 → parpadeo.
    if (this._speed < 0.01) {
      this.mat.emissiveIntensity = this._intensity * 6.0;
      return;
    }
    const hz = this._speed * this.maxStrobeHz;
    this._phase += dt * hz;
    const on = (this._phase % 1.0) < 0.4;
    this.mat.emissiveIntensity = on ? this._intensity * 8.0 : 0.0;
  }
}

// ── Dimmer / PAR convencional — carcasa metálica + lente emisiva ─
class Dimmer {
  constructor(fx) {
    this.fixtureId = fx.id;
    this.group = new THREE.Group();
    this.group.position.set(fx.position[0], fx.position[1] || 4.0, fx.position[2]);

    // Carcasa siempre visible (cilindro metálico oscuro)
    const bodyGeom = new THREE.CylinderGeometry(0.18, 0.22, 0.25, 12);
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0x2a2a2a, roughness: 0.6, metalness: 0.5,
    });
    const body = new THREE.Mesh(bodyGeom, bodyMat);
    body.position.y = 0.12;
    this.group.add(body);

    // Lente emisiva (plano frontal)
    const lensGeom = new THREE.CircleGeometry(0.16, 16);
    this.mat = new THREE.MeshStandardMaterial({
      color: 0x000000,
      emissive: 0xffffff,
      emissiveIntensity: 0.0,
      side: THREE.DoubleSide,
    });
    const lens = new THREE.Mesh(lensGeom, this.mat);
    lens.rotation.x = -Math.PI / 2;
    this.group.add(lens);

    this.channels = new Set(['dim']);
  }
  setIntensity(v) { this.mat.emissiveIntensity = Math.max(0, Math.min(1, v)) * 6.0; }
  setColor(r, g, b) { this.mat.emissive.setRGB(r, g, b); }
  setPan(_)  {}
  setTilt(_) {}
  setSpeed(_) {}
  update(_dt) {}
}

// Diagnóstico: cuenta mensajes DMX recibidos y los muestra cada 60.
let _dmxMsgCount = 0;
let _dmxLastLog = 0;

// ── Aplicar estado DMX recibido por WS a movers/strobes ──────────
function applyDmxState(fixturesState) {
  _dmxMsgCount++;
  const now = performance.now();
  if (now - _dmxLastLog > 2000) {
    _dmxLastLog = now;
    const keys = Object.keys(fixturesState);
    console.log(`[viewer3d] DMX msgs: ${_dmxMsgCount} (${keys.length} fixtures: ${keys.join(', ')})`);
    if (keys.length > 0) {
      const sample = fixturesState[keys[0]];
      console.log(`  sample ${keys[0]}:`, sample);
    }
    console.log(`  movers map (${movers.length}):`, movers.map(m => m.fixtureId));
  }
  // fixturesState = {fixture_id: {channel_name: 0..1}}
  for (const m of movers) {
    const state = fixturesState[m.fixtureId];
    if (!state) continue;

    // Position (movers; strobes ignoran)
    // v1.9 F8: si pan/tilt vienen ambos en 0 exactos, el servidor está
    // mandando el buffer DMX vacío (no hay clip channel position ni manual
    // override). En ese caso NO sobreescribir la pose actual del mover —
    // mantiene la pose inicial (tilt 64°, hacia el stage) en vez de saltar
    // a -90° (cielo) que era el bug que ocultaba los movers visualmente.
    const panRaw  = state.pan  ?? null;
    const tiltRaw = state.tilt ?? null;
    const skipPos = (panRaw === 0 && tiltRaw === 0);
    if (!skipPos) {
      if (panRaw !== null && typeof m.setPan === 'function') {
        // 0..1 → -max/2 .. +max/2 (centro = 0.5). Reducimos a 0.6x del
        // máximo para que pan típico (0.3-0.7) gire menos extremamente.
        const maxPan = (m.maxPanDeg || 540) * 0.6;
        m.setPan((panRaw - 0.5) * maxPan);
      }
      if (tiltRaw !== null && typeof m.setTilt === 'function') {
        // v1.9 F10: mapping comprimido para que tilt SIEMPRE apunte hacia
        // el stage en el rango típico de los clips position (0.3-0.7).
        //   tilt=0.0 → 10° (casi horizontal hacia frente)
        //   tilt=0.5 → 55° (perfecto hacia stage, abajo-frente)
        //   tilt=1.0 → 100° (recto hacia abajo)
        // Antes la fórmula `tilt * 270 - 90` mandaba tilt=0.72 a 104° (hacia
        // el fondo, fuera de cámara) o tilt=0 a -90° (al cielo).
        m.setTilt(tiltRaw * 90 + 10);
      }
    }

    // Color (RGB directo o color_wheel mapeado a paleta básica)
    let r = 1, g = 1, b = 1;
    let hasColor = false;
    if ('r' in state || 'g' in state || 'b' in state) {
      r = state.r ?? 0;
      g = state.g ?? 0;
      b = state.b ?? 0;
      hasColor = (r + g + b) > 0.001;
    }
    if (hasColor && typeof m.setColor === 'function') {
      m.setColor(r, g, b);
    } else if (typeof m.setColor === 'function') {
      // Sin color → blanco para que el dim sea visible
      m.setColor(1, 1, 1);
    }

    // Intensity (dim o intensity).
    // shutter: solo atenúa si viene explícitamente abierto (>0). El valor
    // por defecto DMX es 0 (obturador cerrado) pero en un simulador eso
    // apaga todos los movers que no tengan clip de shutter — no deseado.
    // Tratamos shutter=0 como "no asignado" → no atenuar.
    let dim = 1.0;
    if ('dim' in state) dim = state.dim;
    else if ('intensity' in state) dim = state.intensity;
    if ('shutter' in state && state.shutter > 0) dim *= state.shutter;
    if (typeof m.setIntensity === 'function') m.setIntensity(dim);

    // Speed (strobe)
    if ('speed' in state && typeof m.setSpeed === 'function') {
      m.setSpeed(state.speed);
    }
  }
}

// ── WebSocket: recibe frames RGB ─────────────────────────────────
let ws = null;
let wsReconnectTimer = null;

function connectWS() {
  try {
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      wsStatusEl.textContent = 'OK';
      wsStatusEl.className = 'ws-on';
      console.log(`[viewer3d] WS conectado a ${WS_URL}`);
    };

    ws.onclose = () => {
      wsStatusEl.textContent = 'OFF';
      wsStatusEl.className = 'ws-off';
      console.log(`[viewer3d] WS cerrado, reintento en 2s`);
      // Apagar barras
      bars.forEach(b => b.setAllBlack());
      if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(connectWS, 2000);
    };

    ws.onerror = (e) => {
      console.warn(`[viewer3d] WS error:`, e);
    };

    ws.onmessage = (ev) => {
      // Dos tipos de mensaje:
      //   • ArrayBuffer binario → frame RGB de barras LED.
      //   • String (texto JSON) → estado DMX de movers/strobes/etc.
      //                          {"type":"dmx","fixtures":{...}}
      if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data);
          if (msg && msg.type === 'dmx' && msg.fixtures) {
            applyDmxState(msg.fixtures);
          } else if (msg && msg.type === 'reload_layout') {
            loadLayout();
          }
        } catch (e) {
          console.warn(`[viewer3d] JSON inválido en WS:`, e);
        }
        return;
      }
      // Binary path — frame RGB
      try {
        const buf = new Uint8Array(ev.data);
        const expected = bars.length * (bars[0]?.numLeds || LEDS_PER_BAR) * 3;
        if (buf.length !== expected) {
          console.warn(`[viewer3d] frame size inesperado: ${buf.length} vs ${expected}`);
          return;
        }
        const ledsPerBar = bars[0].numLeds;
        for (let b = 0; b < bars.length; b++) {
          const offset = b * ledsPerBar * 3;
          const view = buf.subarray(offset, offset + ledsPerBar * 3);
          bars[b].setRGB(view);
        }
      } catch (e) {
        console.error(`[viewer3d] Error procesando frame:`, e);
      }
    };
  } catch (e) {
    console.error(`[viewer3d] WS connect falló:`, e);
    wsReconnectTimer = setTimeout(connectWS, 2000);
  }
}

// ── FPS counter ──────────────────────────────────────────────────
let lastFpsT = performance.now();
let frameCount = 0;

function updateFPS(now) {
  frameCount++;
  if (now - lastFpsT > 500) {
    const fps = (frameCount * 1000) / (now - lastFpsT);
    fpsEl.textContent = fps.toFixed(0);
    lastFpsT = now;
    frameCount = 0;
  }
}

// ── Render loop ──────────────────────────────────────────────────
let _lastT = performance.now();
function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min(0.1, (now - _lastT) / 1000);
  _lastT = now;
  controls.update();
  // Actualizar movers (uniforms time + dir del beam)
  for (const m of movers) m.update(dt, camera);
  composer.render();
  updateFPS(now);
}

// ── Resize handler ───────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});

// ── Boot ─────────────────────────────────────────────────────────
(async () => {
  await loadLayout();
  connectWS();
  animate();
})();
