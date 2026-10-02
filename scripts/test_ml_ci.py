"""Probe CI: Chrome headed bajo Xvfb + perfil persistente contra el listado de ML.

Igual que test_ml_profile.py pero sin espera de captcha manual: en el runner
no hay quien lo resuelva. Hasta 3 intentos con esperas; el veredicto va a
stdout (busqueda de "VEREDICTO:") y el exit code dice el resultado:
  0 = listado ok (con N recargas limpias)
  1 = muro/captcha
  2 = pagina de error de ML
  3 = timeout sin veredicto claro
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://listado.mercadolibre.com.uy/inmuebles/casas/venta/montevideo/"
PROFILE = Path(os.environ.get("ML_PROFILE_DIR", "/tmp/ml-chrome-profile"))
CHANNEL = os.environ.get("ML_CHROME_CHANNEL", "").strip() or None
MAX_WAIT_S = 45  # por intento


async def state(page) -> str:
    html = await page.content()
    if "abuse-china-wall" in html or "recaptcha" in html.lower():
        return "muro"
    if "ui-search-layout__item" in html or "andes-money-amount" in html:
        return "ok"
    if "Hubo un error" in html:
        return "error"
    return "otro"


async def esperar_ok(page) -> str:
    last = ""
    for i in range(MAX_WAIT_S // 5):
        s = await state(page)
        if s != last:
            print(f"[{i * 5}s] estado: {s}", flush=True)
            last = s
        if s in ("ok", "muro", "error"):
            return s
        await page.wait_for_timeout(5_000)
    return last or "otro"


async def main() -> int:
    print(f"perfil: {PROFILE} (existe={PROFILE.exists()}) channel={CHANNEL}", flush=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,  # headed: bajo Xvfb en CI, ventana real en local
            channel=CHANNEL,
            locale="es-UY",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        final = "otro"
        for intento in (1, 2, 3):
            print(f"--- intento {intento} ---", flush=True)
            await page.goto(URL, wait_until="commit", timeout=30_000)
            final = await esperar_ok(page)
            if final == "ok":
                break
            print(f"intento {intento}: {final}; reintentando...", flush=True)

        if final != "ok":
            print(f"\nVEREDICTO: {final.upper()}", flush=True)
            await ctx.close()
            return {"muro": 1, "error": 2}.get(final, 3)

        html = await page.content()
        ids = set(re.findall(r"MLU\d{6,}", html))
        print(f"\nLISTADO OK: {len(ids)} ids MLU unicos, {len(html) // 1024} KB", flush=True)

        # 2 recargas para verificar que el perfil pasa sin captcha otra vez
        for n in (1, 2):
            await page.reload(wait_until="commit")
            await page.wait_for_timeout(6_000)
            s = await state(page)
            print(f"recarga {n}: {s}", flush=True)
            if s != "ok":
                print(f"\nVEREDICTO: OK_PERO_RECARGA_{n}_{s.upper()}", flush=True)
                await ctx.close()
                return 3

        print("\nVEREDICTO: OK_HEADLESS_RUNNER_VIABLE", flush=True)
        await ctx.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
