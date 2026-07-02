"""
Crea el proyecto 'pista_patinaje' (techo sala de patinaje) y pone todos los
focos a focus via el bridge MCP en ws://127.0.0.1:9876.

Layout del techo (vista cenital):
  Sala: 24 m × 14 m  |  Techo: Y = 8.0 m

  Z = -6.0  [spot_00  spot_01  spot_02  spot_03  spot_04]   ← fila spots frontal
  Z = -4.5  [wash_00  wash_01  wash_02  wash_03  wash_04]
  Z = -1.5  [wash_05  wash_06  wash_07  wash_08  wash_09]
  Z =  1.5  [wash_10  wash_11  wash_12  wash_13  wash_14]
  Z =  4.5  [wash_15  wash_16  wash_17  wash_18  wash_19]
  Z =  6.0  [spot_05  spot_06  spot_07  spot_08  spot_09]   ← fila spots trasera

  X cols:   -9.0   -4.5    0.0    4.5    9.0

Focus position = pan central + tilt 90° abajo + dim full + shutter abierto.
  - pan   = 0.50  (0° = centro)
  - tilt  = 0.333 (90° / max_tilt 270° = apunta al suelo)
  - dim   = 1.00
  - shutter = 1.00
  - wash: zoom = 0.70 (abierto)
  - spot: focus = 0.50 (foco nítido medio), gobo_wheel = 0.00 (disco abierto)

Uso:
  cd show-designer
  python scripts/crear_pista_patinaje.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

# ── rutas ────────────────────────────────────────────────────────────────────
REPO = Path(__file__).parent.parent
PROJECT_SLUG = "pista_patinaje"
PROJECT_DIR = REPO / "projects" / PROJECT_SLUG
BRIDGE_URL = "ws://127.0.0.1:9876"

# ── geometría del techo ───────────────────────────────────────────────────────
CEILING_Y = 8.0
X_COLS = [-9.0, -4.5, 0.0, 4.5, 9.0]
WASH_Z_ROWS = [-4.5, -1.5, 1.5, 4.5]   # 4 filas × 5 cols = 20 wash
SPOT_Z_ROWS = [-6.0, 6.0]              # 2 filas × 5 cols = 10 spots

# ── focus values ──────────────────────────────────────────────────────────────
FOCUS_COMMON = {"pan": 0.5, "pan_fine": 0.0, "tilt": 0.333, "tilt_fine": 0.0,
                "dim": 1.0, "shutter": 1.0}
FOCUS_WASH   = {**FOCUS_COMMON, "zoom": 0.70}
FOCUS_SPOT   = {**FOCUS_COMMON, "focus": 0.50, "gobo_wheel": 0.0}


# ── generador de fixtures ──────────────────────────────────────────────────────

def _build_fixtures() -> list[dict]:
    fixtures = []

    # — WASHES —
    wash_idx = 0
    for z in WASH_Z_ROWS:
        for x in X_COLS:
            fid = f"wash_{wash_idx:02d}"
            dmx_start = wash_idx * 15 + 1          # 15 ch cada uno, universo 1
            fixtures.append({
                "fixture_id": fid,
                "profile_id": "generic_wash_15ch",
                "universe": 1,
                "dmx_start": dmx_start,
                "position": [round(x, 3), CEILING_Y, round(z, 3)],
                "rotation": [0.0, 0.0, 0.0],
                "label": f"Wash {wash_idx:02d}",
                "legacy_bar_idx": None,
                "target_ip": None,
                "manual_channels": FOCUS_WASH,
            })
            wash_idx += 1

    # — SPOTS —
    spot_idx = 0
    for z in SPOT_Z_ROWS:
        for x in X_COLS:
            fid = f"spot_{spot_idx:02d}"
            dmx_start = spot_idx * 18 + 1          # 18 ch cada uno, universo 2
            fixtures.append({
                "fixture_id": fid,
                "profile_id": "generic_beam_18ch",
                "universe": 2,
                "dmx_start": dmx_start,
                "position": [round(x, 3), CEILING_Y, round(z, 3)],
                "rotation": [0.0, 0.0, 0.0],
                "label": f"Spot {spot_idx:02d}",
                "legacy_bar_idx": None,
                "target_ip": None,
                "manual_channels": FOCUS_SPOT,
            })
            spot_idx += 1

    return fixtures


def _write_project_files(fixtures: list[dict]) -> None:
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    # project.json
    project = {
        "slug": PROJECT_SLUG,
        "name": "Pista de Patinaje — Sidney",
        "audio_path": "",
        "analysis_slug": "",
        "created": "2026-06-13T00:00:00",
        "notes": (
            "Techo sala de patinaje: 20 wash (generic_wash_15ch, universo 1) "
            "+ 10 spots (generic_beam_18ch, universo 2). "
            "Rectángulo 24 m × 14 m, altura 8 m. "
            "Focus: pan=0, tilt=90° abajo, dim=full, shutter open."
        ),
    }
    (PROJECT_DIR / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # rig.json
    rig = {"version": 1, "fixtures": fixtures}
    (PROJECT_DIR / "rig.json").write_text(
        json.dumps(rig, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # show.json vacío
    show = {
        "version": 2,
        "duration_ms": 180000,
        "clips": [],
        "groups": [],
        "cue_points": [{"slot": 1, "time_ms": 0, "name": "Inicio", "color": "#00BFFF"}],
        "markers": [],
    }
    (PROJECT_DIR / "show.json").write_text(
        json.dumps(show, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[OK] Proyecto escrito en {PROJECT_DIR}")
    print(f"     {len([f for f in fixtures if 'wash' in f['fixture_id']])} wash  "
          f"+ {len([f for f in fixtures if 'spot' in f['fixture_id']])} spots")


# ── MCP bridge: set_fixture_channel ──────────────────────────────────────────

async def _rpc(ws, method: str, params: dict) -> dict:
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    await ws.send(json.dumps(msg))
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    return json.loads(raw).get("result", {})


async def _set_focus_via_bridge(fixtures: list[dict]) -> None:
    try:
        import websockets
    except ImportError:
        print("[SKIP] websockets no instalado — focus ya está en rig.json manual_channels")
        return

    print(f"\n[MCP] Conectando a {BRIDGE_URL} …")
    try:
        async with websockets.connect(BRIDGE_URL, open_timeout=3) as ws:
            ok_count = 0
            for fx in fixtures:
                fid = fx["fixture_id"]
                channels = fx["manual_channels"]
                for ch_name, value in channels.items():
                    result = await _rpc(ws, "set_fixture_channel", {
                        "fixture_id": fid,
                        "channel_name": ch_name,
                        "value": value,
                    })
                    if result.get("ok"):
                        ok_count += 1
            print(f"[MCP] {ok_count} canales puestos a focus en la sesión activa.")
            # Guardar rig si el servidor cargó este proyecto
            save_r = await _rpc(ws, "save_rig", {})
            if save_r.get("ok"):
                print(f"[MCP] Rig guardado — {save_r.get('fixtures')} fixtures.")
            else:
                print(f"[MCP] save_rig: {save_r}")
    except (OSError, ConnectionRefusedError):
        print("[MCP] Bridge no disponible en :9876 — focus ya escrito en rig.json.")
    except Exception as e:
        print(f"[MCP] Error: {e}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    fixtures = _build_fixtures()
    _write_project_files(fixtures)
    asyncio.run(_set_focus_via_bridge(fixtures))

    print("\n── SIGUIENTE PASO ───────────────────────────────────────────────")
    print("  Para cargar este proyecto, arranca el servidor con:")
    print(f"    set LUCES_PROJECT={PROJECT_SLUG}")
    print("    python -m server.main")
    print("─────────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
