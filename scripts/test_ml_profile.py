"""Prueba decisiva: perfil persistente de Chrome + captcha manual una vez.

Abre una ventana con perfil persistente, va al listado de ML. Si aparece el
muro de seguridad, el usuario lo resuelve a mano y el script detecta cuando
cargan los items. Después recarga 2 veces para verificar que las cookies
dejan pasar corridas siguientes sin captcha.
"""
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://listado.mercadolibre.com.uy/inmuebles/casas/venta/montevideo/"
PROFILE = Path("/tmp/ml-chrome-profile")


async def state(page) -> str:
    html = await page.content()
    if "ui-search-layout__item" in html or "andes-money-amount" in html:
        return "ok"
    if "abuse-china-wall" in html or "recaptcha" in html.lower():
        return "muro"
    if "Hubo un error" in html:
        return "error"
    return "otro"


async def main() -> int:
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE),
            channel="chrome",
            headless=False,
            locale="es-UY",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(URL, wait_until="commit", timeout=30_000)

        print("\nEsperando que la página muestre items (o que resuelvas el captcha)...")
        last = ""
        for i in range(60):  # hasta 5 minutos con captcha manual
            s = await state(page)
            if s != last:
                print(f"[{i*5}s] estado: {s}")
                last = s
            if s == "ok":
                break
            await page.wait_for_timeout(5_000)

        if s != "ok":
            print(f"No cargó el listado (estado final: {s}).")
            await ctx.close()
            return 1

        html = await page.content()
        import re
        ids = set(re.findall(r"MLU\d{6,}", html))
        print(f"\nLISTADO OK: {len(ids)} ids MLU únicos, {len(html)//1024} KB")
        print("\nRecargando 2 veces para verificar que el perfil pasa sin captcha...")
        for n in (1, 2):
            await page.reload(wait_until="commit")
            await page.wait_for_timeout(6_000)
            s2 = await state(page)
            print(f"recarga {n}: {s2}")
            if s2 != "ok":
                await ctx.close()
                return 1

        print("\nRESULTADO: el perfil persistente pasa las 3 corridas. "
              "La vía Mac+Chrome real es viable.")
        await ctx.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
