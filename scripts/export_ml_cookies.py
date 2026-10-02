"""Exporta las cookies del perfil local de Chrome (perfil del probe) a un
JSON de Playwright (storage_state), sin imprimir valores sensibles.

Sirve para decidir si vale la pena trasplantar las cookies al runner de
Actions: si el perfil tiene sesion logueada, el trasplante puede marcar la
cuenta; si son solo cookies de visitante, el riesgo es bajo.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE = Path(os.environ.get("ML_PROFILE_DIR", "/tmp/ml-chrome-profile"))
OUT = Path(os.environ.get("ML_STORAGE_STATE_OUT", "/tmp/ml-storage-state.json"))

# Dominios que nos interesan (ML + google analytics interno de ML).
DOMINIOS = ("mercadolibre", "mercadolibre.com", "meli")


async def main() -> int:
    if not PROFILE.exists():
        print(f"perfil no existe: {PROFILE}")
        return 1
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=True,  # solo para leer cookies; no navegamos
        )
        cookies = await ctx.cookies()
        await ctx.close()

    ml = [c for c in cookies if any(d in c.get("domain", "") for d in DOMINIOS)]
    print(f"cookies totales: {len(cookies)} | de ML: {len(ml)}")

    # Resumen seguro: nombre, dominio, expira, httpOnly. NUNCA el valor.
    for c in sorted(ml, key=lambda c: c.get("domain", "")):
        exp = c.get("expires", -1)
        vida = "sesion" if exp == -1 else f"{(exp - __import__('time').time()) / 86400:.0f} dias"
        print(f"  {c['name'][:32]:34} {c['domain'][:28]:30} {vida:>10} httpOnly={c.get('httpOnly')}")

    # Detectar sesion logueada: ML usa cookies de sesion largas para usuario.
    largas = [c for c in ml if c.get("expires", -1) > 0 and c["expires"] - __import__("time").time() > 86400 * 20]
    print(f"\ncookies con >20 dias de vida: {len(largas)} -> {'POSIBLE SESION LOGUEADA' if largas else 'perfil anonimo'}")

    OUT.write_text(json.dumps({"cookies": ml, "origins": []}, indent=1), encoding="utf-8")
    print(f"\nexportado a {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
