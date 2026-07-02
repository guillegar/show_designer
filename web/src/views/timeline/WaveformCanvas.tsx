// WaveformCanvas.tsx — B1: forma de onda del audio en el ruler del timeline.
// Autónomo (ADR-005 / despiece de Timeline.tsx): posee su fetch + su dibujo.
// El backend puede responder {status:"computing"} (librosa corre en un executor
// para no congelar el tick) y avisar después con el evento 'waveform_ready'
// por el stream → se reintenta (ya cache hit).
import { useEffect, useRef, useState } from "react";
import { control } from "../../api/control";
import { stream } from "../../api/stream";

type WaveformData = {
  peaks_max: number[];
  peaks_min: number[];
  n_buckets: number;
  duration_sec: number;
};

export function WaveformCanvas({ show, zoom, duration, width }: {
  show: boolean; zoom: number; duration: number; width: number;
}) {
  const [data, setData] = useState<WaveformData | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Fetch bajo demanda (+ reintento al llegar 'waveform_ready')
  useEffect(() => {
    if (!show || data) return;
    let cancelled = false;
    const fetchWf = () => {
      control.call("get_waveform", {}).then((r: any) => {
        if (!cancelled && r?.ok && Array.isArray(r.peaks_max)) setData(r);
      }).catch(() => {});
    };
    fetchWf();
    const off = stream.onWaveformReady(fetchWf);
    return () => { cancelled = true; off(); };
  }, [show, data]);

  // Redibujo al cambiar zoom o datos
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data || !show) return;
    const { peaks_max, peaks_min, n_buckets } = data;
    const cw = Math.round(duration * zoom);
    const ch = 38;
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const mid = ch / 2;
    const scale = mid * 0.88;
    ctx.fillStyle = "rgba(80,210,130,0.4)";
    for (let x = 0; x < cw; x++) {
      const b0 = Math.floor((x / cw) * n_buckets);
      const b1 = Math.min(Math.ceil(((x + 1) / cw) * n_buckets), n_buckets);
      let pmax = 0, pmin = 0;
      for (let b = b0; b < b1; b++) {
        if (peaks_max[b] > pmax) pmax = peaks_max[b];
        if (peaks_min[b] < pmin) pmin = peaks_min[b];
      }
      const yTop = Math.floor(mid - pmax * scale);
      const yBot = Math.ceil(mid - pmin * scale);
      ctx.fillRect(x, yTop, 1, Math.max(1, yBot - yTop));
    }
  }, [show, data, zoom, duration]);

  if (!show) return null;
  return (
    <canvas
      ref={canvasRef}
      style={{ position: "absolute", top: 0, left: 0, width, height: "100%", pointerEvents: "none", zIndex: 0 }}
    />
  );
}
