# Configuración (env vars y `output_targets.json`)

## Variables de entorno (`LUCES_*`)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `LUCES_PROJECT` | primer proyecto (alfabético) | Slug del proyecto a cargar al arrancar (`projects/<slug>/`). Lo usan los launchers `Luces *.bat`. |
| `LUCES_LOG_LEVEL` | `INFO` | Nivel del logger (`DEBUG`/`INFO`/`WARNING`/`ERROR`). Ver `src/log.py`. |
| `LUCES_LOG_FILE` | (sin archivo) | Ruta de log rotativo (o `1` → `./luces.log`). |
| `LUCES_AUTOSAVE_INTERVAL` | `60` | Segundos entre autosaves del show. |
| `LUCES_NO_MCP_COMPAT` | (desactivado) | Si está definida, NO abre el compat MCP en `:9876` (útil en tests). |
| `LUCES_NO_PILLOW` | (desactivado) | Fuerza el fallback sin Pillow en el preview de efectos. |

Ejemplo:

```powershell
$env:LUCES_PROJECT   = "red_sun"
$env:LUCES_LOG_LEVEL = "DEBUG"
$env:LUCES_LOG_FILE  = "luces.log"
python -m server.main
```

## `output_targets.json` (routing de salida + credenciales de entorno)

Vive en la raíz y define **a dónde va cada universo** (WLED / nodo Art-Net / sACN / USB /
simulación) — separado del rig (`rig.json`). Las claves numéricas (`"1"`..`"11"`) son universos.

Además admite campos **específicos del entorno / sensibles**:

| Clave | Contenido | Sensible |
|---|---|---|
| `api_key` | API key de la REST API `/api/v1` (`X-API-Key`) | 🔒 sí |
| `tokens` | tokens de multiusuario `[{token, role}]` | 🔒 sí |
| `webhooks` | endpoints + `secret` (HMAC) | 🔒 sí |
| `secret` | secreto de firma | 🔒 sí |
| `marketplace_url` | URL del manifiesto de plugins | no |

> ⚠️ **Seguridad:** el `output_targets.json` versionado **no debe contener secretos**. Los `tokens`,
> `api_key` y `secret` son propios de cada instalación. Si vas a usarlos, mantenlos fuera de git
> (p. ej. un `output_targets.local.json` gitignoreado o variables de entorno). El export de *bundle*
> ya sustituye estos campos por placeholders (`show_bundle.py`).

Sin `tokens` configurados, **todos los handlers son accesibles sin autenticación** (modo desarrollo
local); el backend lo avisa al arrancar (`warn_if_no_tokens`). El host por defecto es `127.0.0.1`
(no expuesto a la LAN salvo `--host 0.0.0.0`).
