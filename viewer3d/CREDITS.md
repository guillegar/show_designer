# Créditos del Viewer 3D

## Software original utilizado

### ASLS Studio
- **Repositorio**: https://github.com/ASLS-org/studio
- **Autor**: Tim Kadel (@benkuper colaborador)
- **Licencia**: GPL-3.0
- **Uso en este viewer**: referencia conceptual del visualizer 3D. La escena
  Three.js de este proyecto está inspirada en el módulo
  `src/plugins/visualizer/` de ASLS Studio pero reescrita desde cero
  para nuestro modelo de fixtures más simple (LED strips primero).

### Three.js
- **Repositorio**: https://github.com/mrdoob/three.js
- **Licencia**: MIT
- **Uso**: rendering 3D core (geometrías, materiales, OrbitControls)

## Componentes inspirados (no portados literalmente)

### `viewer3d/moving_head.js` (2026-05-29)
- **Inspiración**: `src/plugins/visualizer/moving_head.js` y shaders
  `src/plugins/visualizer/shaders/beam.vertex.glsl` + `beam.fragment.glsl`
  de ASLS Studio.
- **Lo que se replicó conceptualmente** (sin copiar código):
  - Arquitectura jerárquica base → yoke (pan) → head (tilt) → beam
  - Idea de un cilindro deformado en cono via vertex shader según ángulo
  - Falloff radial + longitudinal en el fragment shader
  - Componente de "glare" cuando miras el beam de frente
  - Uniform para color/intensidad/dirección del beam
- **Lo que se hizo distinto** (decisión propia):
  - Shader original con menos sofisticación matemática (sin simplex noise 3D,
    sin HSV manipulation, sin físicamente correct decay)
  - Sin instanced geometry (cada mover es su propia mesh) — simplifica
  - Hash 2D propio en lugar de simplex noise para el polvo
  - Mesh de yoke/head con cajas + cilindros básicos en vez de modelos GLB
  - API más simple: setPan/setTilt/setColor/setIntensity/setBeamAngle

## Pendientes a inspirar de ASLS Studio cuando haga falta

- `src/plugins/visualizer/grid.js` → suelo infinito con shader custom
  (Author original: Fyrestar, https://github.com/Fyrestar/THREE.InfiniteGridHelper).
  Lo añadiremos cuando queramos vista de escenario más grande.
- `src/plugins/visualizer/controls.js` → presets de cámara (front, top, side).
  Lo añadiremos cuando los usuarios pidan navegación rápida.

## Licencia del proyecto

Este viewer3d se publica bajo **GPL-3.0** (compatible con el código fuente
de ASLS Studio del que se inspira/porta).
