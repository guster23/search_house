"""Prueba rapida: Playwright headless pasa la puerta de verificacion de ML?"""
import asyncio
import sys
import time

from playwright.async_api import async_playwright

URL = "https://listado.mercadolibre.com.uy/inmuebles/casas/venta/montevideo/"


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="es-UY",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        t0 = time.time()
        try:
            await page.goto(URL, wait_until="commit", timeout=20_000)
            await page.wait_for_timeout(6000)
        except Exception as exc:
            print(f"goto fallo: {exc}")
            await browser.close()
            return 1

        url_final = page.url
        html = await page.content()
        await browser.close()

    print(f"tardo {time.time() - t0:.1f}s")
    print(f"URL final: {url_final[:110]}")
    print(f"bytes: {len(html)}")
    print(f"account-verification: {html.count('account-verification')}")
    print(f"suspicious-traffic: {html.count('suspicious-traffic')}")
    print(f"items de listado: {html.count('ui-search-layout__item')}")
    print(f"precios: {html.count('poly-component__price')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
