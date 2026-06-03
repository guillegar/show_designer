# Luces — Frontend Web (v1.10)

Frontend React + TypeScript (Vite) de Luces. Habla con el backend headless
(`server/`, Python) por WebSocket: control JSON-RPC (`/ws/control`) y stream de
frames/estado (`/ws/stream`).

## Desarrollo

```bash
# 1) Backend headless (desde la raíz del repo)
python -m server.main            # http://localhost:8000

# 2) Frontend en modo dev (este directorio)
npm install
npm run dev                      # http://localhost:5173 (proxea WS a :8000)
```

## Producción

```bash
npm run build                    # genera web/dist
python -m server.main            # sirve web/dist en http://localhost:8000
```

## Estructura

- `src/api/control.ts` — cliente JSON-RPC (promesa por id, reconexión).
- `src/api/stream.ts` — decodifica el frame binario (10×93×3) + estado + dmx.
- `src/store.ts` — estado global (zustand): transporte + listas cacheadas (refetch
  cuando cambia `rev`, p.ej. tras una edición por UI o por Claude/MCP).
- `src/components/` — Transport, Scrubber.
- `src/views/` — Timeline, Live, Analyzer, Patch (cableadas a datos reales).
- `src/styles*.css` — sistema de diseño (portado del handoff, oklch nativo).

Los canvas de Live/Patch leen el frame RGB real del backend en su propio
`requestAnimationFrame` (no recalculan la luz en el navegador).
