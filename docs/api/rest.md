# API REST — /api/v1/

Endpoints REST para integrar Show Designer con sistemas externos (QLab, scripts, control de sala) sin WebSocket persistente.

## Autenticación

Si `output_targets.json["api_key"]` está configurada, todos los endpoints requieren el header:

```
X-API-Key: tu_clave_secreta
```

Sin clave configurada, la API es abierta (útil en desarrollo local).

Respuesta sin clave o con clave incorrecta: **HTTP 401**
```json
{"ok": false, "error": "X-API-Key inválida o ausente"}
```

## Formato de respuesta

```json
{"ok": true, "data": {...}}
{"ok": false, "error": "descripción del error"}
```

---

## Endpoints

### GET /api/v1/status

Estado actual del transport.

```bash
curl http://localhost:8000/api/v1/status
```

Respuesta:
```json
{
  "ok": true,
  "data": {"t_ms": 12345, "playing": true, "bpm": 120.0, "section": "coro"}
}
```

---

### GET /api/v1/clips

Lista de clips con paginación.

```bash
curl "http://localhost:8000/api/v1/clips?offset=0&limit=20"
```

Parámetros:
- `offset` (int, default 0)
- `limit` (int, default 100)

---

### POST /api/v1/clips

Crear un nuevo clip.

```bash
curl -X POST http://localhost:8000/api/v1/clips \
  -H "Content-Type: application/json" \
  -d '{"track": 0, "start_ms": 1000, "end_ms": 5000, "effect_id": 1004}'
```

Respuesta: **HTTP 201** con el clip creado.

---

### GET /api/v1/cues

Estado actual de la lista de cues.

```bash
curl http://localhost:8000/api/v1/cues
```

---

### POST /api/v1/cues/go

Avanzar al siguiente cue.

```bash
curl -X POST http://localhost:8000/api/v1/cues/go \
  -H "X-API-Key: mi_clave"
```

---

### POST /api/v1/macros/{name}

Activar una macro por nombre.

```bash
curl -X POST http://localhost:8000/api/v1/macros/brightness \
  -H "Content-Type: application/json" \
  -d '{"value": 0.75}'
```

---

### GET /api/v1/fixtures

Lista de fixtures del rig activo.

```bash
curl http://localhost:8000/api/v1/fixtures
```

---

## Configurar api_key

En `output_targets.json`:
```json
{
  "api_key": "mi_clave_secreta_aquí",
  "artnet": {...}
}
```

Dejar vacío o ausente = sin autenticación.
