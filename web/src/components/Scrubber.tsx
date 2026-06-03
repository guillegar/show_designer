import { useMemo, useRef } from "react";
import { control } from "../api/control";
import { useStore } from "../store";

export function Scrubber() {
  const ref = useRef<HTMLDivElement>(null);
  const t = useStore((s) => s.t);
  const duration = useStore((s) => s.duration) || 1;
  const sections = useStore((s) => s.sections);
  const pct = (t / duration) * 100;

  // waveform estática decorativa (igual que el prototipo)
  const bars = useMemo(
    () => Array.from({ length: 160 }, (_, i) => {
      const env = 0.35 + 0.65 * Math.abs(Math.sin(i * 0.4) * Math.cos(i * 0.13));
      const drop = (i > 52 && i < 78) || (i > 118 && i < 146) ? 1.25 : 1;
      return Math.min(1, env * drop);
    }),
    []
  );

  const onClick = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const nt = ((e.clientX - r.left) / r.width) * duration;
    control.call("seek", { t_sec: Math.max(0, Math.min(duration, nt)) });
  };

  return (
    <div className="tp-scrub">
      <div className="scrub-track" ref={ref} onClick={onClick}>
        <svg className="scrub-wave" preserveAspectRatio="none" viewBox="0 0 160 40">
          {bars.map((h, i) => (
            <rect key={i} x={i + 0.15} y={20 - h * 18} width="0.7" height={h * 36} fill="var(--txt-3)" />
          ))}
        </svg>
        <div className="scrub-sections">
          {sections.map((s, i) => (
            <div key={i} className="scrub-sec" style={{ left: (s.start / duration) * 100 + "%" }}>
              <span>{s.name}</span>
            </div>
          ))}
        </div>
        <div className="scrub-fill" style={{ width: pct + "%" }} />
        <div className="scrub-head" style={{ left: pct + "%" }} />
      </div>
    </div>
  );
}
