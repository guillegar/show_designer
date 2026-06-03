// icons.tsx — iconos geométricos SVG (port de app.jsx::Ico).
import { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;

export const Ico = {
  timeline: (p: P) => (
    <svg viewBox="0 0 16 16" {...p}>
      <rect x="1.5" y="3" width="9" height="2.4" rx="1.2" fill="currentColor" />
      <rect x="5" y="6.8" width="9.5" height="2.4" rx="1.2" fill="currentColor" />
      <rect x="2.5" y="10.6" width="7" height="2.4" rx="1.2" fill="currentColor" />
    </svg>
  ),
  live: (p: P) => (
    <svg viewBox="0 0 16 16" {...p}>
      <g fill="currentColor">
        <rect x="2" y="2.5" width="2.2" height="11" rx="1.1" />
        <rect x="6.9" y="2.5" width="2.2" height="11" rx="1.1" />
        <rect x="11.8" y="2.5" width="2.2" height="11" rx="1.1" />
      </g>
    </svg>
  ),
  analyzer: (p: P) => (
    <svg viewBox="0 0 16 16" {...p} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M1 8 H3 L4.5 3 L6.5 13 L8 6 L9.5 10.5 L11 8 H15" />
    </svg>
  ),
  patch: (p: P) => (
    <svg viewBox="0 0 16 16" {...p} fill="currentColor">
      {[3.5, 8, 12.5].flatMap((y) =>
        [3.5, 8, 12.5].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.7" />)
      )}
    </svg>
  ),
  play: (p: P) => (<svg viewBox="0 0 16 16" {...p}><path d="M4 2.5 L13 8 L4 13.5 Z" fill="currentColor" /></svg>),
  pause: (p: P) => (<svg viewBox="0 0 16 16" {...p}><rect x="3.5" y="3" width="3" height="10" rx="1" fill="currentColor" /><rect x="9.5" y="3" width="3" height="10" rx="1" fill="currentColor" /></svg>),
  stop: (p: P) => (<svg viewBox="0 0 16 16" {...p}><rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="currentColor" /></svg>),
  toStart: (p: P) => (<svg viewBox="0 0 16 16" {...p} fill="currentColor"><rect x="2.5" y="3" width="2" height="10" rx="1" /><path d="M13 3.5 L6 8 L13 12.5 Z" /></svg>),
  rec: (p: P) => (<svg viewBox="0 0 16 16" {...p}><circle cx="8" cy="8" r="5" fill="currentColor" /></svg>),
  loop: (p: P) => (
    <svg viewBox="0 0 16 16" {...p} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M3 6 a5 5 0 0 1 9-1 M13 10 a5 5 0 0 1-9 1" />
      <path d="M11.5 3.5 L12.5 5.2 L10.6 5.4 Z" fill="currentColor" stroke="none" />
      <path d="M4.5 12.5 L3.5 10.8 L5.4 10.6 Z" fill="currentColor" stroke="none" />
    </svg>
  ),
  save: (p: P) => (<svg viewBox="0 0 16 16" {...p} fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M3 3h8l2 2v8H3z" /><rect x="5" y="3" width="5" height="3.5" fill="currentColor" stroke="none" /></svg>),
  gear: (p: P) => (
    <svg viewBox="0 0 16 16" {...p} fill="currentColor">
      <path d="M8 5.5A2.5 2.5 0 1 0 8 10.5 2.5 2.5 0 0 0 8 5.5Zm0 1.5a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z" />
      <path d="M7 1h2l.3 1.6 1.3.55 1.4-.9 1.4 1.4-.9 1.4.55 1.3L14.6 7v2l-1.6.3-.55 1.3.9 1.4-1.4 1.4-1.4-.9-1.3.55L9 14.6H7l-.3-1.6-1.3-.55-1.4.9-1.4-1.4.9-1.4L2.95 9.3 1.4 9V7l1.6-.3.55-1.3-.9-1.4 1.4-1.4 1.4.9 1.3-.55Z" opacity="0.5" />
    </svg>
  ),
  check: (p: P) => (<svg viewBox="0 0 16 16" {...p} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8.5 L6.5 12 L13 4" /></svg>),
};

export const fmtTime = (s: number) => {
  s = Math.max(0, s);
  const m = Math.floor(s / 60);
  const ss = Math.floor(s % 60);
  return `${m}:${String(ss).padStart(2, "0")}`;
};
export const fmtTimeMs = (s: number) => {
  s = Math.max(0, s);
  const m = Math.floor(s / 60);
  const ss = Math.floor(s % 60);
  const ms = Math.floor((s % 1) * 1000);
  return `${m}:${String(ss).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
};
