"""
handlers/feedback.py — feedback log de la vista Live + waveform peaks del Analyzer (ADR-005).
"""
from __future__ import annotations


# ── Feedback log (vista Live) — persiste en projects/<slug>/feedback.json ────
def _feedback_path(session):
    return session.project.folder / "feedback.json"


def _h_list_feedback(session, params):
    import json
    p = _feedback_path(session)
    if not p.is_file():
        return {"entries": []}
    try:
        with open(p, encoding="utf-8") as f:
            return {"entries": json.load(f)}
    except Exception:
        return {"entries": []}


def _h_add_feedback(session, params):
    import json
    p = _feedback_path(session)
    entries = _h_list_feedback(session, {})["entries"]
    entry = {
        "t": float(params.get("t", session.time)),
        "section": params.get("section", session.section_name_at(session.time)),
        "text": params.get("text", ""),
        "cats": params.get("cats", {}),
        "pos": bool(params.get("pos", True)),
    }
    entries.append(entry)
    entries.sort(key=lambda e: e["t"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    return {"ok": True, "entry": entry, "count": len(entries)}


# ── Waveform peaks (vista Analyzer) ─────────────────────────────────────────
def _h_analyzer_waveform_peaks(session, params):
    buckets = int(params.get("buckets", 1100))
    try:
        dur = session.duration or session.analysis.summary.get("duration_s", 0)
        rng = session.analysis.features_range(0.0, dur, downsample_to=buckets, names=["rms"])
        rms = rng.get("features", {}).get("rms", []) or []
        if rms:
            mx = max(rms) or 1.0
            peaks = [round(min(1.0, v / mx), 4) for v in rms]
        else:
            peaks = []
        return {"peaks": peaks, "duration": dur, "bpm": session.bpm}
    except Exception as e:
        return {"peaks": [], "error": str(e)}


HANDLERS = {
    "list_feedback": _h_list_feedback,
    "add_feedback": _h_add_feedback,
    "analyzer_waveform_peaks": _h_analyzer_waveform_peaks,
}
