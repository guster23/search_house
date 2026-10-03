#!/usr/bin/env python3
"""Sonda de Gallito desde el runner de GitHub Actions.

Pregunta que responde: es Gallito accesible desde una IP de datacenter?

Esto NO evade nada: no rota identidades, no usa proxies, no resuelve
challenges. Solo mide tres clientes distintos desde el runner y reporta que
ve cada uno:

  1. httpx  -- lo que usa house-watch hoy
  2. curl   -- otra huella TLS/HTTP
  3. Chrome real headed bajo Xvfb (Playwright)

Contexto: el docstring de gallito.py declara la fuente bloqueada por
Cloudflare, pero esa medicion (2026-09-25) fue con httpx desde una IP
residencial. Nunca se midio desde el runner ni con un navegador real.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

URLS = [
    "https://www.gallito.com.uy/robots.txt",
    "https://www.gallito.com.uy/sitemap.xml",
    "https://www.gallito.com.uy/sitemap-venta-casas.xml",
    "https://www.gallito.com.uy/inmuebles/venta",
    "https://www.gallito.com.uy/venta-casa-la-blanqueada-montevideo-4-dormitorios-inmuebles-29165314",
]

# Titulos de la pagina intersticial de Cloudflare (es/en).
INTERSTITIAL_TITLES = ("just a moment", "un momento", "attention required")


def _classify(
    status: int | None, body: str, cf_mitigated: str | None, title: str = ""
) -> str:
    """Distingue una pagina real de la intersticial de Cloudflare.

    Ojo: Cloudflare embebe scripts de challenge tambien en paginas que si
    cargan, asi que buscar 'challenge' en el body da falsos positivos. La
    senal buena es el status + el titulo de la intersticial.
    """
    if status is None:
        return "ERROR"
    if cf_mitigated == "challenge":
        return "CHALLENGE"
    low_title = title.lower()
    if any(t in low_title for t in INTERSTITIAL_TITLES):
        return "CHALLENGE"
    if status == 403:
        return "CHALLENGE"
    if status == 200:
        return "OK"
    return f"HTTP_{status}"


def probe_httpx() -> list[dict]:
    import httpx

    out = []
    headers = {"User-Agent": UA, "Accept-Language": "es-UY,es;q=0.9"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=20) as client:
        for url in URLS:
            try:
                r = client.get(url)
                out.append(
                    {
                        "url": url,
                        "status": r.status_code,
                        "len": len(r.text),
                        "cf_mitigated": r.headers.get("cf-mitigated"),
                        "verdict": _classify(r.status_code, r.text, r.headers.get("cf-mitigated")),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                out.append({"url": url, "status": None, "error": str(exc), "verdict": "ERROR"})
    return out


def probe_curl() -> list[dict]:
    out = []
    for url in URLS:
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-A", UA, url],
                capture_output=True,
                text=True,
                timeout=25,
            )
            code = int(r.stdout.strip() or 0)
            out.append({"url": url, "status": code, "verdict": _classify(code, "", None)})
        except Exception as exc:  # noqa: BLE001
            out.append({"url": url, "status": None, "error": str(exc), "verdict": "ERROR"})
    return out


def probe_chrome(runs: int = 1, delay_s: float = 0.0) -> list[dict]:
    """Corre el navegador real `runs` veces para medir estabilidad del challenge.

    Cada corrida usa un contexto nuevo (cookies/clearance frescos) para ver si
    el challenge se resuelve de forma consistente desde la misma IP, o si es
    azaroso. Se agrega un campo `run` (1-indexado) a cada medicion.
    """
    out: list[dict] = []
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"playwright no disponible: {exc}", "verdict": "SKIP"}]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=False,  # headed bajo Xvfb: el caso mas favorable
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as exc:  # noqa: BLE001
            return [{"error": f"no se pudo lanzar Chrome: {exc}", "verdict": "SKIP"}]

        for run in range(1, runs + 1):
            if run > 1 and delay_s:
                time.sleep(delay_s)
            context = browser.new_context(user_agent=UA, locale="es-UY")
            page = context.new_page()
            for url in URLS:
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # Da tiempo a que el challenge de Cloudflare se resuelva solo.
                    page.wait_for_timeout(6000)
                    html = page.content()
                    status = resp.status if resp else None
                    title = page.title()
                    out.append(
                        {
                            "run": run,
                            "url": url,
                            "status": status,
                            "title": title,
                            "len": len(html),
                            "verdict": _classify(status, html, None, title),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    out.append(
                        {"run": run, "url": url, "status": None, "error": str(exc), "verdict": "ERROR"}
                    )
            context.close()
        browser.close()
    return out


def _stability(rows: list[dict]) -> dict:
    """Cuenta veredictos por URL para ver si el resultado es consistente."""
    per_url: dict[str, dict[str, int]] = {}
    for r in rows:
        url = r.get("url")
        if not url:
            continue
        verdict = r.get("verdict", "ERROR")
        per_url.setdefault(url, {})[verdict] = per_url.setdefault(url, {}).get(verdict, 0) + 1
    return per_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda de accesibilidad de Gallito")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Corridas del navegador real para medir estabilidad del challenge (default 1).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Segundos entre corridas del navegador (default 10).",
    )
    args = parser.parse_args()
    runs = max(1, args.repeat)

    chrome = probe_chrome(runs=runs, delay_s=args.delay)
    report = {
        "probe": "gallito",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "httpx": probe_httpx(),
        "curl": probe_curl(),
        "chrome_headed": chrome,
        "stability": _stability(chrome),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    verdicts = {r.get("verdict") for r in report["httpx"] + report["curl"] + chrome}
    ok = "OK" in verdicts
    print(f"\nVEREDICTO: {'ACCESIBLE' if ok else 'BLOQUEADO'}  (verdicts={sorted(verdicts)})")
    if runs > 1:
        print(f"ESTABILIDAD (chrome_headed, {runs} corridas):")
        for url, counts in report["stability"].items():
            summary = ", ".join(f"{v}={n}" for v, n in sorted(counts.items()))
            print(f"  {url}  ->  {summary}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
