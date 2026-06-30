// control.test.ts — Manejo del token de acceso (L3, revisión de seguridad).
// El token NO debe quedar en la URL (historial/Referer): se migra a sessionStorage.
import { describe, it, expect, beforeEach } from "vitest";
import { resolveToken } from "./control";

const TOKEN_KEY = "show_designer_token";

describe("resolveToken (token fuera de la URL)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    history.replaceState(null, "", "/");
  });

  it("migra ?token= de la URL a sessionStorage y lo quita de la URL", () => {
    history.replaceState(null, "", "/?token=abc123&tab=timeline");
    const t = resolveToken();
    expect(t).toBe("abc123");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("abc123");
    // el token ya no aparece en la URL...
    expect(location.search).not.toContain("token=");
    // ...pero el resto de parámetros se conserva
    expect(location.search).toContain("tab=timeline");
  });

  it("lee el token de sessionStorage cuando no está en la URL", () => {
    sessionStorage.setItem(TOKEN_KEY, "stored-xyz");
    expect(resolveToken()).toBe("stored-xyz");
  });

  it("devuelve cadena vacía si no hay token en ningún sitio", () => {
    expect(resolveToken()).toBe("");
  });
});
