"""
test_show_bundle.py — Tests de backup y restauración completa de show (N2).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.show_bundle import export_show_bundle, import_show_bundle


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_session(tmp_path: Path, slug: str = "test_show") -> MagicMock:
    """Sesión mínima con estructura de proyecto en disco."""
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True)

    show_data = {"schema_version": 4, "clips": [], "groups": [], "cues": []}
    (project_dir / "show.json").write_text(json.dumps(show_data), encoding="utf-8")

    autovj_data = {"rules": [], "active": False}
    (project_dir / "autovj.json").write_text(json.dumps(autovj_data), encoding="utf-8")

    session = MagicMock()
    session.project.slug = slug
    session.project.audio_file = str(tmp_path / "projects" / slug / "audio.mp3")
    return session


def _make_output_targets(tmp_path: Path):
    ot = {
        "api_key": "secret-api-key-123",
        "tokens": [{"token": "tok-abc", "role": "operator"}],
        "webhooks": [{"url": "http://x.com/hook", "secret": "my-secret"}],
    }
    ot_path = tmp_path / "output_targets.json"
    ot_path.write_text(json.dumps(ot), encoding="utf-8")
    return ot_path


# ─── tests ───────────────────────────────────────────────────────────────────

def test_export_bundle_creates_zip_with_manifest(tmp_path, monkeypatch):
    """export_show_bundle → ZIP existe y contiene show.json y MANIFEST.json."""
    monkeypatch.chdir(tmp_path)
    session = _make_session(tmp_path)
    _make_output_targets(tmp_path)

    path = export_show_bundle(session)

    assert Path(path).exists()
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert "show.json" in names
        assert "MANIFEST.json" in names


def test_export_bundle_excludes_audio_by_default(tmp_path, monkeypatch):
    """export_show_bundle(include_audio=False) → ZIP no contiene el audio."""
    monkeypatch.chdir(tmp_path)
    session = _make_session(tmp_path)
    # Crear archivo de audio pequeño
    audio_path = tmp_path / "projects" / "test_show" / "audio.mp3"
    audio_path.write_bytes(b"\xff\xfb" * 100)
    session.project.audio_file = str(audio_path)
    _make_output_targets(tmp_path)

    path = export_show_bundle(session, include_audio=False)

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert not any(n.startswith("audio/") for n in names)


def test_export_bundle_sanitizes_credentials(tmp_path, monkeypatch):
    """output_targets.json en el bundle no contiene el api_key original."""
    monkeypatch.chdir(tmp_path)
    session = _make_session(tmp_path)
    _make_output_targets(tmp_path)

    path = export_show_bundle(session)

    with zipfile.ZipFile(path) as zf:
        if "output_targets.json" in zf.namelist():
            ot = json.loads(zf.read("output_targets.json").decode("utf-8"))
            assert ot.get("api_key") != "secret-api-key-123"
            assert "<PLACEHOLDER" in ot.get("api_key", "")
            tokens = ot.get("tokens", [])
            if tokens:
                assert tokens[0].get("token") != "tok-abc"


def test_import_bundle_restores_project(tmp_path, monkeypatch):
    """import_show_bundle → proyecto registrado con clips correctos."""
    monkeypatch.chdir(tmp_path)
    session = _make_session(tmp_path, slug="original_show")
    _make_output_targets(tmp_path)

    # Exportar
    bundle_path = export_show_bundle(session)

    # Importar en un dir de proyectos vacío
    import_dir = tmp_path / "imported_projects"
    import_dir.mkdir()
    slug, warnings = import_show_bundle(bundle_path, import_dir)

    assert slug  # no vacío
    restored_show = import_dir / slug / "show.json"
    assert restored_show.exists()
    data = json.loads(restored_show.read_text("utf-8"))
    assert "clips" in data


def test_import_corrupted_zip_returns_error(tmp_path, monkeypatch):
    """ZIP corrupto → import_show_bundle lanza ValueError sin crear proyecto parcial."""
    monkeypatch.chdir(tmp_path)
    bad_zip = tmp_path / "corrupt.zip"
    bad_zip.write_bytes(b"NOT A ZIP FILE")

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    with pytest.raises(ValueError, match="corrupto|inválido"):
        import_show_bundle(str(bad_zip), projects_dir)

    # No se creó ningún subdirectorio de proyecto
    assert not any(projects_dir.iterdir())


def test_import_bundle_with_unknown_plugin_warns(tmp_path, monkeypatch):
    """Bundle con plugin declarado pero sin archivo → warning en la lista."""
    monkeypatch.chdir(tmp_path)

    # Crear ZIP manualmente con plugin faltante en el ZIP pero declarado en MANIFEST
    zip_path = tmp_path / "bundle_no_plugin.zip"
    show_data = {"schema_version": 4, "clips": [], "groups": [], "cues": []}
    manifest = {
        "version": "1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "show_slug": "ghost_show",
        "sd_version": "2.0",
        "plugins": ["missing_effect.py"],
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("show.json", json.dumps(show_data))
        zf.writestr("MANIFEST.json", json.dumps(manifest))
        # NO incluimos plugins/effects/missing_effect.py

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    slug, warnings = import_show_bundle(str(zip_path), projects_dir)

    assert any("missing_effect.py" in w for w in warnings)
