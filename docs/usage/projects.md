# Multi-Project Guide 📁

Organize your light shows into separate projects.

## Project Structure

Each project lives in `projects/<slug>/`:

```
projects/el_taser/
├── project.json      # Metadata (name, audio_path, analysis_slug, notes)
├── show.json         # Secuencia de efectos (timeline + clips/patterns/cues)
├── rig.json          # Rig (fixtures)
├── rig_layout.json   # Posiciones 3D del rig (visor 3D)
├── presets.json      # Banco de presets del proyecto
├── autovj.json       # Reglas Auto-VJ
└── feedback.json     # Historial de feedback en vivo
```

La **canción** vive fuera de la carpeta: el audio en la ruta de `audio_path` y el
análisis en `analizadas/<analysis_slug>/`. Así, un proyecto = **canción + rig +
secuencia + presets + auto-VJ**, y cada una de esas piezas se puede intercambiar.

## La pestaña «Proyectos» (web)

La pestaña **Proyectos** (primera en la barra de pestañas) es el centro de gestión:
galería para cargar proyectos enteros, intercambio de componentes sueltos, y
creación/copia de proyectos. (El desplegable ▾ junto al nombre del proyecto en la
topbar sigue disponible para cambio rápido.)

### Cargar un proyecto entero

En la **galería**, cada tarjeta muestra la canción (título · BPM · duración), el
nº de fixtures del rig, el nº de clips de la secuencia y badges de presets/auto-VJ.
Pulsa **«Cargar»** → carga **todo** el paquete (canción + rig + secuencia + presets +
auto-VJ) sin reiniciar el servidor. El proyecto activo aparece marcado **«activo /
Cargado»**.

### Intercambiar componentes sueltos

Despliega **«Intercambiar componentes en el proyecto activo»**. Hay una lista por
componente — **Rigs · Secuencias · Presets · Auto-VJ · Canciones** — agregando los de
todos los proyectos (las canciones incluyen también las de `analizadas/` sin usar).
**«Aplicar»** intercambia solo esa pieza sobre el proyecto cargado:

- **Rig** y **Presets** y **Auto-VJ** se persisten en el proyecto activo al instante.
- **Secuencia** se intercambia en memoria (como cualquier edición del timeline); usa
  Guardar (Ctrl+S) o el autosave para conservarla.
- **Canción**: re-temporiza el show (los beats/duración de la nueva canción difieren).

### Crear un proyecto nuevo (compositor)

Pulsa **«+ Nuevo proyecto»**. Pon un nombre y, por cada componente (Canción, Rig,
Secuencia, Presets, Auto-VJ), elige de **qué proyecto** sale (o déjalo vacío). Marca
«Cargar al crear» si quieres abrirlo al terminar. El slug se deriva del nombre
(seguro, sin colisiones).

### Duplicar y cambiar un componente

En una tarjeta, **«Duplicar…»** copia el proyecto a un slug nuevo (solo los archivos
de contenido). Opcionalmente, sustituye **un** componente por el de otro proyecto.

## Importing Audio

For each project, you can analyze audio automatically:

1. Place `.mp3` file in project folder
2. App detects it and auto-analyzes (takes ~30s)
3. Analysis cached as `analizadas/<song>/`

## Exporting a Project

1. **Toolbar** → Export button (📤)
2. Choose format:
   - **QLC+ XML** — Import into QLC+ software
   - **CSV** — Clips or DMX frames
3. Saved to `projects/<slug>/exports/`

## Backing Up

Projects are just JSON files. Back them up:

```powershell
# Copy to external drive
xcopy projects\ E:\backup\shows\ /Y /I /E
```

## Advanced: Editing project.json

You can manually edit `projects/<slug>/project.json`:

```json
{
  "slug": "el_taser",
  "name": "El Taser de Mamá Remix",
  "audio_path": "C:\\...\\El Taser de Mama Remix.mp3",
  "analysis_slug": "el_taser_de_mama_remix",
  "created": "2026-05-29T12:34:56",
  "notes": "..."
}
```

El BPM y la duración salen del análisis (`analizadas/<analysis_slug>/analysis.json`),
no de `project.json`. Guarda y recarga para aplicar cambios.

---

**Next**: Check [Hardware Guide](../hardware.md) to connect physical lights to your project.
