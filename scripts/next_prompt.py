#!/usr/bin/env python3
"""
next_prompt.py — Genera automáticamente el prompt para la siguiente fase del ROADMAP v3.

Uso:
    python scripts/next_prompt.py
    python scripts/next_prompt.py --fase F2        # forzar una fase concreta
    python scripts/next_prompt.py --out prompt.txt  # guardar en archivo

El script:
  1. Lee git log para detectar la última fase aplicada.
  2. Lee ROADMAP_v3.md para encontrar la siguiente fase pendiente.
  3. Extrae el contenido completo de esa fase.
  4. Añade contexto (tests actuales, modelo recomendado) y genera el prompt.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

# Orden canónico de fases (puede haber combinadas como "E3+E4")
PHASE_ORDER = [
    "E1", "E2", "E3", "E4",
    "F1", "F2", "F3", "F4",
    "G1", "G2", "G3", "G4",
    "H1", "H2", "H3", "H4",
    "I1", "I2", "I3", "I4", "I5",
    "J1", "J2", "J3", "J4",
    "K1", "K2", "K3",
    "L1", "L2", "L3",
    "M1", "M2", "M3",
    "N1", "N2",
]

# Fases que conviene agrupar en un solo prompt (se implementan juntas)
GROUPED = {
    "E3": ["E3", "E4"],
}

# Modelo recomendado por fase (extraído del ROADMAP_v3.md, duplicado aquí para acceso rápido)
MODELS = {
    "E1": "Sonnet", "E2": "Sonnet", "E3": "Haiku", "E4": "Sonnet",
    "F1": "Sonnet", "F2": "Sonnet", "F3": "Haiku", "F4": "Sonnet",
    "G1": "Sonnet", "G2": "Sonnet", "G3": "Opus",  "G4": "Haiku",
    "H1": "Sonnet", "H2": "Haiku",  "H3": "Sonnet", "H4": "Sonnet",
    "I1": "Sonnet", "I2": "Haiku",  "I3": "Sonnet", "I4": "Opus",  "I5": "Haiku",
    "J1": "Sonnet", "J2": "Opus",   "J3": "Sonnet", "J4": "Haiku",
    "K1": "Opus",   "K2": "Opus",   "K3": "Sonnet",
    "L1": "Sonnet", "L2": "Haiku",  "L3": "Opus",
    "M1": "Sonnet", "M2": "Opus",   "M3": "Sonnet",
    "N1": "Sonnet", "N2": "Haiku",
}

MODEL_CMD = {
    "Opus":   "claude --model claude-opus-4-8",
    "Sonnet": "claude --model claude-sonnet-4-6",
    "Haiku":  "claude --model claude-haiku-4-5",
}


# ── Git helpers ───────────────────────────────────────────────────────────────

def git_log_phases():
    """Devuelve lista de IDs de fase ya aplicadas, en orden de más reciente a más antigua."""
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=REPO, capture_output=True, text=True
    )
    applied = []
    for line in result.stdout.splitlines():
        # Detecta: "roadmap-v3 fase F1:", "roadmap-v3 fases E3+E4:"
        m = re.search(r"roadmap-v3 fases? ([A-Z0-9+]+):", line)
        if m:
            ids = m.group(1).split("+")
            applied.extend(ids)
    return applied


def current_test_count():
    """Intenta extraer el número de tests verdes del último commit de roadmap-v3."""
    result = subprocess.run(
        ["git", "log", "--oneline", "-20"],
        cwd=REPO, capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "roadmap-v" in line:
            sha = line.split()[0]
            msg = subprocess.run(
                ["git", "show", "--format=%B", "-s", sha],
                cwd=REPO, capture_output=True, text=True
            ).stdout
            m = re.search(r"(\d{3,4}) verdes", msg)
            if m:
                return int(m.group(1))
    return "???"


# ── ROADMAP parser ────────────────────────────────────────────────────────────

def load_roadmap():
    """Lee ROADMAP_v3.md y devuelve dict {fase_id: contenido_completo}."""
    path = REPO / "ROADMAP_v3.md"
    if not path.exists():
        sys.exit("ERROR: ROADMAP_v3.md no encontrado en la raíz del repo.")
    text = path.read_text(encoding="utf-8")

    sections = {}
    # Busca encabezados ## X1 — Nombre (~N días, Modelo)
    pattern = re.compile(r"^## ([A-Z]\d+) — (.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(text))

    for i, m in enumerate(matches):
        fase_id = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[fase_id] = text[start:end].strip()

    return sections


def is_applied(section_text):
    """Detecta si la sección tiene marca de aplicada."""
    return "✅ APLICADA" in section_text or "APLICADA" in section_text.split("\n")[0]


def next_phase(applied_ids, sections):
    """Devuelve el ID de la siguiente fase no aplicada."""
    for phase_id in PHASE_ORDER:
        if phase_id in applied_ids:
            continue
        if phase_id in sections and is_applied(sections[phase_id]):
            continue
        return phase_id
    return None


# ── Prompt builder ────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """\
Lee CLAUDE.md §0 TL;DR y ROADMAP_v3.md §{phases_str} completo{'s' if len(phases) > 1 else ''}.
Tu tarea es implementar la{'s' if len(phases) > 1 else ''} Fase{'s' if len(phases) > 1 else ''} {phases_str}.

CONTEXTO: {context_line}
El proyecto de referencia es el_taser (273.3 s, 30 FPS, 10 barras WLED 93 LEDs c/u).
Invariantes I1-I5 del ROADMAP.md siguen vigentes sin excepción.

{section_content}

CHECKLIST DE CIERRE:
[ ] pytest tests/ verde ({tests} + nuevos)
[ ] npx tsc --noEmit limpio + npm run build OK (si toca web)
[ ] ROADMAP_v3.md: {phases_str} → APLICADA con fecha. CLAUDE.md actualizado.
[ ] Commit: "roadmap-v3 fase {phases_str}: {commit_title}"
"""


def build_prompt(phases, sections, tests, applied_ids):
    phases_str = "+".join(phases)
    context_parts = []
    for pid in applied_ids[:6]:  # últimas 6 aplicadas para contexto
        if pid in sections:
            first_line = sections[pid].split("\n")[0]
            context_parts.append(pid)
    context_line = f"Fases {'+'.join(context_parts)} aplicadas ({tests} tests verdes)." if context_parts else f"{tests} tests verdes."

    combined_content = []
    for phase_id in phases:
        if phase_id in sections:
            combined_content.append(sections[phase_id])

    # Título del commit: primera línea del primer ## encabezado
    commit_title = ""
    if phases and phases[0] in sections:
        first_line = sections[phases[0]].split("\n")[0]
        m = re.search(r"## [A-Z]\d+ — (.+?)(?:\s*[~(✅]|$)", first_line)
        if m:
            commit_title = m.group(1).strip().lower()

    prompt = f"Lee CLAUDE.md §0 TL;DR y ROADMAP_v3.md §{phases_str} completo"
    if len(phases) > 1:
        prompt += "s"
    prompt += ".\nTu tarea es implementar la"
    if len(phases) > 1:
        prompt += "s"
    prompt += " Fase"
    if len(phases) > 1:
        prompt += "s"
    prompt += f" {phases_str}.\n\n"
    prompt += f"CONTEXTO: {context_line}\n"
    prompt += "El proyecto de referencia es el_taser (273.3 s, 30 FPS, 10 barras WLED 93 LEDs c/u).\n"
    prompt += "Invariantes I1-I5 del ROADMAP.md siguen vigentes sin excepción.\n\n"
    prompt += "═" * 60 + "\n"
    prompt += "\n\n".join(combined_content)
    prompt += "\n" + "═" * 60 + "\n\n"
    prompt += "CHECKLIST DE CIERRE:\n"
    prompt += f"[ ] pytest tests/ verde ({tests} + nuevos)\n"
    prompt += "[ ] npx tsc --noEmit limpio + npm run build OK (si toca web)\n"
    prompt += f"[ ] ROADMAP_v3.md: {phases_str} → APLICADA con fecha. CLAUDE.md actualizado.\n"
    prompt += f'[ ] Commit: "roadmap-v3 fase {phases_str}: {commit_title}"\n'

    return prompt


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera el prompt para la siguiente fase del ROADMAP v3.")
    parser.add_argument("--fase", help="Forzar una fase concreta (ej. F2)")
    parser.add_argument("--out", help="Guardar prompt en este archivo")
    args = parser.parse_args()

    applied_ids = git_log_phases()
    tests = current_test_count()
    sections = load_roadmap()

    # Determinar qué fase(s) implementar
    if args.fase:
        target = args.fase.upper()
        phases = GROUPED.get(target, [target])
    else:
        target = next_phase(applied_ids, sections)
        if not target:
            print("✅ ¡Todas las fases del ROADMAP v3 están aplicadas!")
            sys.exit(0)
        phases = GROUPED.get(target, [target])

    model = MODELS.get(phases[0], "Sonnet")
    cmd = MODEL_CMD[model]

    print(f"\n{'='*60}")
    print(f"  SIGUIENTE FASE: {'+'.join(phases)}")
    print(f"  MODELO:         {model}")
    print(f"  COMANDO:        {cmd}")
    print(f"  TESTS ACTUALES: {tests} verdes")
    print(f"{'='*60}\n")

    prompt = build_prompt(phases, sections, tests, applied_ids)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(prompt, encoding="utf-8")
        print(f"Prompt guardado en: {out_path.resolve()}")
    else:
        print(prompt)

    print(f"\n{'='*60}")
    print(f"  Arranca con:  {cmd}")
    print("  Luego pega el prompt de arriba.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
