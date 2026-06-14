import { useState, useCallback } from "react";
import { control } from "../api/control";
import { useStore } from "../store";
import { Ico, fmtTime } from "../icons";
import { Scrubber } from "./Scrubber";

// M1: Tap BPM — estado local del componente Transport
function TapButton() {
  const [taps, setTaps] = useState(0);
  const [bpm, setBpm] = useState<number | null>(null);

  const tap = useCallback(async () => {
    try {
      const r: any = await control.call("tap_bpm", {});
      setTaps(r.taps ?? 0);
      if (r.ready && r.bpm != null) setBpm(r.bpm);
    } catch { /* I4 */ }
  }, []);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <button
        className="tp-btn"
        style={{ fontSize: 10, fontWeight: 700, padding: "0 8px", minWidth: 36 }}
        onClick={tap}
        title="Tap Tempo (T)"
      >
        TAP
      </button>
      <div style={{ display: "flex", gap: 2 }}>
        {[1, 2, 3, 4].map((i) => (
          <span key={i} style={{
            width: 5, height: 5, borderRadius: "50%",
            background: taps >= i ? "var(--acc)" : "var(--bg-1)",
            border: "1px solid var(--line)",
          }} />
        ))}
      </div>
      {bpm != null && (
        <span style={{ fontSize: 10, color: "var(--acc)", minWidth: 38 }}>
          {bpm.toFixed(1)}
        </span>
      )}
    </div>
  );
}

export function Transport() {
  const { t, playing, duration, loop, rec, section, bar, beat } = useStore();
  const [vol, setVol] = useState(1);

  const togglePlay = () => control.call(playing ? "pause" : "play");
  const toStart = () => control.call("seek", { t_sec: 0 });
  const stop = () => control.call("stop");
  const toggleLoop = () => control.call("set_loop", { on: !loop });
  const toggleRec = () => control.call("set_rec", { on: !rec });

  return (
    <div className="transport">
      <div className="tp-btns">
        <button className="tp-btn" onClick={toStart} title="Inicio"><Ico.toStart width="15" /></button>
        <button className="tp-btn play" onClick={togglePlay} title="Play/Pause">
          {playing ? <Ico.pause width="18" /> : <Ico.play width="18" />}
        </button>
        <button className="tp-btn" onClick={stop} title="Stop"><Ico.stop width="14" /></button>
        <button className="tp-btn" style={loop ? { color: "var(--acc)", borderColor: "var(--acc)" } : undefined}
          onClick={toggleLoop} title="Loop"><Ico.loop width="16" /></button>
        <button className={"tp-btn rec" + (rec ? " on" : "")} onClick={toggleRec} title="Armar grabación">
          <Ico.rec width="12" />
        </button>
      </div>

      <div className="tp-time">
        <span className="cur">{fmtTime(t)}</span>
        <span className="dur">/ {fmtTime(duration)}</span>
      </div>

      <Scrubber />

      <div className="tp-meta">
        <div className="tp-stat"><div className="k">Sección</div><div className="v">{section}</div></div>
        <div className="tp-stat"><div className="k">Compás</div><div className="v beat">{bar}.{beat}</div></div>
        <TapButton />
        <div className="vol" title={`Volumen ${Math.round(vol * 100)}%`}>
          <Ico.live width="14" style={{ color: "var(--txt-3)" }} />
          <input className="rng" type="range" min={0} max={100} value={Math.round(vol * 100)}
            onChange={(e) => { const v = +e.target.value / 100; setVol(v); control.call("set_volume", { value: v }); }} />
        </div>
      </div>
    </div>
  );
}
