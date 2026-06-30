// control.ts — Cliente JSON-RPC 2.0 sobre WebSocket (/ws/control).
// Una promesa por `id`. Reconexión automática. Mismo protocolo que el bridge.

type Pending = { resolve: (v: any) => void; reject: (e: any) => void };

const TOKEN_KEY = "show_designer_token";

function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

// Resuelve el token de acceso (L3). Si llega por ?token= en la URL, lo persiste
// en sessionStorage y lo QUITA de la URL (no dejarlo en el historial ni en el
// header Referer); las siguientes cargas lo leen de sessionStorage.
export function resolveToken(): string {
  try {
    const url = new URLSearchParams(location.search);
    const fromUrl = url.get("token");
    if (fromUrl) {
      sessionStorage.setItem(TOKEN_KEY, fromUrl);
      url.delete("token");
      const qs = url.toString();
      history.replaceState(null, "", location.pathname + (qs ? `?${qs}` : "") + location.hash);
      return fromUrl;
    }
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    // sessionStorage/history pueden no existir (tests/SSR) → fallback a la URL.
    return new URLSearchParams(location.search).get("token") || "";
  }
}

class ControlClient {
  private ws: WebSocket | null = null;
  private seq = 1;
  private pending = new Map<number, Pending>();
  private ready!: Promise<void>;
  private resolveReady!: () => void;
  private hbTimer: ReturnType<typeof setInterval> | null = null;
  onReconnect: (() => void) | null = null;

  constructor() {
    this.resetReady();
    this.connect();
  }

  private resetReady() {
    this.ready = new Promise((r) => (this.resolveReady = r));
  }

  private connect() {
    if (typeof WebSocket === "undefined") return;  // SSR / entornos sin WS
    // L3: token desde sessionStorage (o ?token= en la primera carga).
    const pageToken = resolveToken();
    const controlPath = pageToken ? `/ws/control?token=${encodeURIComponent(pageToken)}` : "/ws/control";
    const ws = new WebSocket(wsUrl(controlPath));
    this.ws = ws;
    ws.onopen = () => {
      this.resolveReady();
      this.startHeartbeat();
      this.onReconnect?.();
    };
    ws.onmessage = (e) => {
      let m: any;
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      const p = this.pending.get(m.id);
      if (p) {
        this.pending.delete(m.id);
        if (m.error) p.reject(new Error(m.error.message || "rpc error"));
        else p.resolve(m.result);
      }
    };
    ws.onclose = () => {
      this.stopHeartbeat();
      this.resetReady();
      // rechazar pendientes para no colgar
      for (const [, p] of this.pending) p.reject(new Error("ws closed"));
      this.pending.clear();
      setTimeout(() => this.connect(), 1000);
    };
    ws.onerror = () => ws.close();
  }

  // Heartbeat: ping cada 30 s; si no llega respuesta en 5 s, la conexión está
  // medio-abierta (TCP colgado, que `onclose` no detecta) → cerrar para disparar
  // la reconexión. Cualquier respuesta (incluso error) cuenta como "viva".
  private startHeartbeat() {
    this.stopHeartbeat();
    this.hbTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      let answered = false;
      const mark = () => { answered = true; };
      this.call("ping").then(mark).catch(mark);
      setTimeout(() => {
        if (!answered && this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.close();
      }, 5000);
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.hbTimer != null) {
      clearInterval(this.hbTimer);
      this.hbTimer = null;
    }
  }

  async call<T = any>(method: string, params: Record<string, any> = {}): Promise<T> {
    await this.ready;
    const id = this.seq++;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws!.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }
}

export const control = new ControlClient();
