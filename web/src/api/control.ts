// control.ts — Cliente JSON-RPC 2.0 sobre WebSocket (/ws/control).
// Una promesa por `id`. Reconexión automática. Mismo protocolo que el bridge.

type Pending = { resolve: (v: any) => void; reject: (e: any) => void };

function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

class ControlClient {
  private ws: WebSocket | null = null;
  private seq = 1;
  private pending = new Map<number, Pending>();
  private ready!: Promise<void>;
  private resolveReady!: () => void;
  onReconnect: (() => void) | null = null;

  constructor() {
    this.resetReady();
    this.connect();
  }

  private resetReady() {
    this.ready = new Promise((r) => (this.resolveReady = r));
  }

  private connect() {
    const ws = new WebSocket(wsUrl("/ws/control"));
    this.ws = ws;
    ws.onopen = () => {
      this.resolveReady();
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
      this.resetReady();
      // rechazar pendientes para no colgar
      for (const [, p] of this.pending) p.reject(new Error("ws closed"));
      this.pending.clear();
      setTimeout(() => this.connect(), 1000);
    };
    ws.onerror = () => ws.close();
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
