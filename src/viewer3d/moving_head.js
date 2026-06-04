/**
 * moving_head.js — Mesh de cabeza móvil con beam volumétrico.
 *
 * Implementación ORIGINAL, escrita desde cero. Arquitectura jerárquica
 * (base → yoke → head → beam) con un cono volumétrico generado por shader
 * (falloff radial + longitudinal).
 *
 * Anatomía:
 *   Group "fixture"
 *     ├─ base (cilindro al suelo del fixture)
 *     └─ Group "yoke" (rota Y = pan)
 *          ├─ brazos laterales
 *          └─ Group "head" (rota X = tilt)
 *               ├─ cabeza (caja con frontal emissive)
 *               └─ beam (cono con shader volumétrico custom)
 *
 * API pública:
 *   const mh = new MovingHead({ color, intensity, angleDeg, beamLength });
 *   mh.group  → THREE.Group para añadir a la scene
 *   mh.setPan(deg)         // 0..540
 *   mh.setTilt(deg)        // -135..+135
 *   mh.setColor(r,g,b)     // 0..1
 *   mh.setIntensity(0..1)
 *   mh.setBeamAngle(deg)   // apertura del cono 5..45
 *   mh.update(dt)          // animación interna (time uniform)
 */
import * as THREE from 'three';


// ────────────────────────────────────────────────────────────────
// Shader del beam — vertex/fragment ORIGINALES
// La idea es: un cilindro hueco que se deforma en cono según ángulo,
// con falloff radial y longitudinal en el fragment.
// ────────────────────────────────────────────────────────────────

const BEAM_VERTEX = /* glsl */`
  varying float vLongT;     // 0 = fuente, 1 = punta lejana
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;

  uniform float uAngleRad;  // mitad de la apertura del cono (radianes)
  uniform float uBeamLen;   // longitud del beam (metros)
  uniform float uTopRadius; // radio en la salida (cabeza del foco)

  void main() {
    // Cilindro source: Y va de -0.5 a +0.5. Mapeamos:
    //   Y=+0.5 → boca del foco (vLongT=0)
    //   Y=-0.5 → punta lejana (vLongT=1)
    vLongT = 0.5 - position.y;

    // Radio progresivo: en la boca = uTopRadius, en la punta = uTopRadius + tan(ang) * len
    float radiusHere = uTopRadius + tan(uAngleRad) * uBeamLen * vLongT;

    // Deformar XZ a ese radio, Y a la longitud del beam
    vec3 pos = vec3(
      position.x * radiusHere * 2.0,   // *2 porque cylinder source es radio 0.5
      position.y * uBeamLen,
      position.z * radiusHere * 2.0
    );

    vec4 worldPos4 = modelMatrix * vec4(pos, 1.0);
    vWorldPos = worldPos4.xyz;
    vWorldNormal = normalize(mat3(modelMatrix) * normal);

    gl_Position = projectionMatrix * viewMatrix * worldPos4;
  }
`;

const BEAM_FRAGMENT = /* glsl */`
  precision highp float;
  varying float vLongT;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;

  uniform vec3 uColor;
  uniform float uIntensity;
  uniform float uTime;
  uniform vec3 uBeamDir;        // dirección del beam en mundo (unitaria, apunta hacia salida)
  uniform float uFogDensity;

  // Hash 2D para polvo flotante
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }

  void main() {
    // (sin discard temprano — algunas GPUs lo manejan mal con additive blending)

    // ── Atenuación longitudinal: brilla en la boca, se apaga lejos ──
    float longFade = exp(-vLongT * 0.85);

    // ── Fresnel del cilindro hueco ──
    vec3 V = normalize(cameraPosition - vWorldPos);
    vec3 N = normalize(vWorldNormal);
    float facing = abs(dot(N, V));

    // Base alta para que SIEMPRE haya algo visible.
    // Con additive blending las dos paredes (front+back) acumulan luminosidad
    // en el centro óptico del beam visto desde cualquier ángulo.
    // v1.9 F11: restaurado a mix(0.9, 1.8) — con 0.65/1.2 el haz quedaba
    // invisible. Multiplicador 1.5 (entre el "deslumbre" de 1.8 y el "tenue" 1.3).
    float wallAlpha = mix(0.9, 1.8, pow(1.0 - facing, 1.2));

    // ── Glare frontal (mirando casi por el eje del beam) ──
    float axial = max(0.0, dot(uBeamDir, V));
    float glare = pow(axial, 4.0) * 1.2;

    // ── Polvo flotante en el aire dentro del beam ──
    float dust = 0.0;
    if (uFogDensity > 0.001) {
      vec2 coord = vWorldPos.xz * 0.7 + uTime * 0.08;
      float n = hash21(floor(coord * 6.0)) * 0.6
              + hash21(floor(coord * 12.0)) * 0.3
              + hash21(floor(coord * 24.0)) * 0.1;
      dust = max(0.0, n - 0.35) * uFogDensity * 1.5;
    }

    // Multiplicador global — 1.5: visible sin deslumbre excesivo.
    float a = (wallAlpha + glare + dust) * longFade * uIntensity * 1.5;

    // Como es additive blending y queremos HDR ⇒ no clamp a 1.0 aquí;
    // el toneMapping ACES Filmic del renderer ya comprime el rango.
    gl_FragColor = vec4(uColor * a, min(a, 1.0));
  }
`;


// ────────────────────────────────────────────────────────────────
// Mesh helpers — geometría compartida (eficiencia)
// ────────────────────────────────────────────────────────────────

const _sharedBaseGeo = new THREE.CylinderGeometry(0.18, 0.20, 0.10, 24);
const _sharedYokeArmGeo = new THREE.BoxGeometry(0.04, 0.36, 0.04);
const _sharedHeadGeo = new THREE.BoxGeometry(0.28, 0.22, 0.28);
const _sharedHeadFrontGeo = new THREE.CircleGeometry(0.12, 24);
// v1.9 F9 — colores tipo "gris metalizado" como fixtures profesionales.
// Antes eran casi-negro (0x1a1a22, 0x222230, 0x101018) → invisibles contra
// fondo 0x06080c con la poca iluminación de la escena "club look".
const _baseMat = new THREE.MeshStandardMaterial({
  color: 0x4a4a55, metalness: 0.6, roughness: 0.5,
});
const _yokeMat = new THREE.MeshStandardMaterial({
  color: 0x55555f, metalness: 0.7, roughness: 0.4,
});
const _headMat = new THREE.MeshStandardMaterial({
  color: 0x404048, metalness: 0.7, roughness: 0.45,
});
// Cilindro source del beam: open-ended, 1×1×1 unitario; el shader lo deforma
const _sharedBeamGeo = new THREE.CylinderGeometry(0.5, 0.5, 1.0, 36, 1, true);


// ────────────────────────────────────────────────────────────────
// MovingHead — clase pública
// ────────────────────────────────────────────────────────────────

export class MovingHead {
  constructor(opts = {}) {
    const {
      color = 0xffffff,
      intensity = 0.0,
      angleDeg = 22.0,
      beamLength = 14.0,
      fogDensity = 0.25,
    } = opts;

    // Group raíz — corresponde a la posición física del fixture
    this.group = new THREE.Group();

    // Base
    const base = new THREE.Mesh(_sharedBaseGeo, _baseMat);
    base.position.y = 0.05;
    this.group.add(base);

    // Yoke — gira en Y (pan)
    this.yoke = new THREE.Group();
    this.yoke.position.y = 0.10;
    this.group.add(this.yoke);
    // Brazos del yoke
    const armL = new THREE.Mesh(_sharedYokeArmGeo, _yokeMat);
    armL.position.set(-0.18, 0.18, 0);
    const armR = new THREE.Mesh(_sharedYokeArmGeo, _yokeMat);
    armR.position.set(+0.18, 0.18, 0);
    this.yoke.add(armL, armR);

    // Head — gira en X (tilt) sobre el yoke
    this.head = new THREE.Group();
    this.head.position.y = 0.36;
    this.yoke.add(this.head);
    const headBox = new THREE.Mesh(_sharedHeadGeo, _headMat);
    this.head.add(headBox);
    // Disco frontal emissive (representa la lente)
    const frontMat = new THREE.MeshStandardMaterial({
      color: 0x000000, emissive: new THREE.Color(color),
      emissiveIntensity: intensity * 4.0,
    });
    this._frontMat = frontMat;
    const front = new THREE.Mesh(_sharedHeadFrontGeo, frontMat);
    front.position.y = -0.115;
    front.rotation.x = Math.PI / 2;
    this.head.add(front);

    // Beam — cono volumétrico
    const beamMat = new THREE.ShaderMaterial({
      vertexShader: BEAM_VERTEX,
      fragmentShader: BEAM_FRAGMENT,
      uniforms: {
        uColor: { value: new THREE.Color(color) },
        uIntensity: { value: intensity },
        uAngleRad: { value: (angleDeg * Math.PI) / 180.0 / 2.0 },
        uBeamLen: { value: beamLength },
        uTopRadius: { value: 0.10 },
        uTime: { value: 0.0 },
        uBeamDir: { value: new THREE.Vector3(0, -1, 0) },
        uFogDensity: { value: fogDensity },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    this._beamMat = beamMat;
    const beam = new THREE.Mesh(_sharedBeamGeo, beamMat);
    // Posicionamos el beam para que su base coincida con la cara frontal de la cabeza
    // El cilindro source es 1m alto centrado en y=0. Lo movemos -beamLength/2 para que
    // su tapa superior esté en y=0 (la salida de la cabeza).
    beam.position.y = -beamLength / 2.0 - 0.115;
    this.head.add(beam);

    this._beam = beam;
    this._beamLength = beamLength;

    // Estado inicial
    this.setPan(0);
    this.setTilt(15);  // ligero tilt hacia abajo por defecto
  }

  setPan(deg) {
    this.yoke.rotation.y = (deg * Math.PI) / 180.0;
  }

  setTilt(deg) {
    this.head.rotation.x = (deg * Math.PI) / 180.0;
  }

  setColor(r, g, b) {
    const c = new THREE.Color(r, g, b);
    this._beamMat.uniforms.uColor.value.copy(c);
    this._frontMat.emissive.copy(c);
  }

  setIntensity(v) {
    const i = Math.max(0, Math.min(1, v));
    this._beamMat.uniforms.uIntensity.value = i;
    this._frontMat.emissiveIntensity = i * 4.0;
  }

  setBeamAngle(deg) {
    this._beamMat.uniforms.uAngleRad.value =
      (deg * Math.PI) / 180.0 / 2.0;
  }

  setBeamLength(len) {
    this._beamLength = len;
    this._beamMat.uniforms.uBeamLen.value = len;
    this._beam.position.y = -len / 2.0 - 0.115;
  }

  setFogDensity(v) {
    this._beamMat.uniforms.uFogDensity.value = v;
  }

  /**
   * Llamar cada frame: actualiza el uniform time y recalcula la dirección
   * del beam en mundo (para el glare frontal del shader).
   */
  update(dt, camera = null) {
    this._beamMat.uniforms.uTime.value += dt;

    // Calcular dirección del beam en world-space.
    // Local: -Y (apunta hacia abajo). Aplicamos rotaciones del head y yoke.
    const dir = new THREE.Vector3(0, -1, 0);
    this.head.getWorldQuaternion(new THREE.Quaternion()).then?.();
    // Más simple: aplicar las dos rotaciones explícitamente
    dir.applyEuler(new THREE.Euler(this.head.rotation.x, 0, 0));
    dir.applyEuler(new THREE.Euler(0, this.yoke.rotation.y, 0));
    this._beamMat.uniforms.uBeamDir.value.copy(dir.normalize());
  }
}
