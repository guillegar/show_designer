"""
create_himno_show.py — Crear el show "Himno de España"

Script para crear un nuevo proyecto con:
- Audio: Himno_Espana.mp3
- Timeline: clips de la bandera española ondeante en todas las barras
- Rig: configuración estándar de 10 barras
"""

import sys
import json
import io
from pathlib import Path

# Forzar UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Agregar src/ al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.io.project_manager import ProjectManager
from src.core.timeline_model import Timeline, Clip
from src.core.fixtures import FixtureRig

def create_himno_project():
    """Crea el proyecto Himno de España"""

    pm = ProjectManager()

    # Ruta del audio
    audio_path = Path(__file__).parent.parent / "Himno_Espana.mp3"

    if not audio_path.exists():
        print(f"[-] Archivo de audio no encontrado: {audio_path}")
        return False

    print(f"[+] Audio encontrado: {audio_path}")

    # Crear el proyecto
    try:
        project = pm.create_project(
            slug="himno_espana",
            name="Himno de España",
            audio_path=str(audio_path),
            analysis_slug="himno_espana",
            notes="Show con bandera española ondeante. Efecto custom ID 1002."
        )
        print(f"[+] Proyecto creado: {project.slug} en {project.folder}")
    except Exception as e:
        print(f"[-] Error creando proyecto: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Cargar o crear rig con las 10 barras estándar
    rig_path = project.rig_file

    # Si no existe, copiar del proyecto El Taser
    if not rig_path.exists():
        source_rig = Path(__file__).parent.parent / "projects" / "el_taser" / "rig.json"
        if source_rig.exists():
            import shutil
            shutil.copy(source_rig, rig_path)
            print(f"✅ Rig copiado desde El Taser")
        else:
            # Crear rig mínimo
            rig = FixtureRig()
            # Las barras ya están por defecto en FixtureRig.__init__
            rig.save(rig_path)
            print(f"✅ Rig creado con barras estándar")

    # Crear timeline con clips de bandera ondeante
    show_path = project.show_file

    # Obtener duración estimada del audio (5 segundos en nuestro caso)
    duration_ms = 5000  # dummy audio es de 5 segundos

    timeline = Timeline(duration_ms=duration_ms)

    # Crear clips globales de bandera ondeante en todo el timeline
    # El efecto ID 1002 es SpanishFlagWaveEffect
    # scope="per_bar" para que afecte a todas las barras

    clip = Clip(
        track=-1,  # -1 = global (todas las barras)
        start_ms=0,
        end_ms=duration_ms,
        effect_id=1002,  # Spanish Flag Wave
        scope="per_bar",
        label="Bandera Ondeante",
        params={
            "wave_speed": 2.0,
            "wave_amplitude": 0.15
        }
    )
    timeline.add(clip)

    # Guardar timeline
    timeline.save(show_path)
    print(f"✅ Timeline creado con {len(timeline.clips)} clip de bandera ondeante")

    # Crear cue points interesantes
    show_data = {
        "version": 2,
        "duration_ms": duration_ms,
        "clips": [c.to_dict() for c in timeline.clips],
        "groups": timeline.groups,
        "cue_points": [
            {
                "slot": 1,
                "time_ms": 0,
                "name": "Inicio",
                "color": "#C60B1E"  # Rojo bandera
            },
            {
                "slot": 2,
                "time_ms": duration_ms - 500,
                "name": "Final",
                "color": "#FFC400"  # Amarillo bandera
            }
        ],
        "markers": []
    }

    with open(show_path, 'w') as f:
        json.dump(show_data, f, indent=2)

    print(f"✅ Show guardado: {show_path}")
    print()
    print("=" * 60)
    print("[*] PROYECTO CREADO EXITOSAMENTE")
    print("=" * 60)
    print(f"Nombre: {project.name}")
    print(f"Slug: {project.slug}")
    print(f"Audio: {audio_path.name}")
    print(f"Directorio: {project.folder}")
    print(f"Duracion: {duration_ms/1000:.1f}s")
    print(f"Efecto: #1002 (Bandera Espanola Ondeante)")
    print()
    print("[*] Para reproducir el show:")
    print("1. Abre http://localhost:8000")
    print("2. Selecciona 'himno_espana'")
    print("3. Presiona Play")
    print()

    return True


if __name__ == "__main__":
    success = create_himno_project()
    sys.exit(0 if success else 1)
