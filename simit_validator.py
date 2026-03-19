"""
SIMIT Validator - Python
=========================
Valida multas e infracciones en el SIMIT Colombia por cedula.
URL: https://www.fcm.org.co/simit/#/estado-cuenta

REQUISITOS:
    pip install playwright
    playwright install chromium

USO:
    python simit_validator.py 1014306477

VARIABLES DE ENTORNO:
    (ninguna requerida - sin captcha)
"""

import sys
import json
import asyncio
from datetime import datetime, timezone

try:
    from playwright.async_api import async_playwright
except ImportError:
    print(json.dumps({"success": False, "error": "Instala: pip install playwright && playwright install chromium"}))
    sys.exit(1)

URL      = "https://www.fcm.org.co/simit/#/estado-cuenta"
TIMEOUT  = 30_000


async def consultar_simit(cedula: str) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
            await page.wait_for_timeout(3000)

            # Buscar campo de busqueda
            campo = None
            selectores = [
                "input[placeholder*='identificaci' i]",
                "input[placeholder*='placa' i]",
                "input[placeholder*='numero' i]",
                "input[placeholder*='número' i]",
                "input[placeholder*='consulta' i]",
                "input#searchInput",
                "input[name='busqueda']",
                "input[name='consulta']",
                "input[name='identificador']",
                ".search-input input",
                ".estado-cuenta input",
                "form input[type='text']",
            ]
            for sel in selectores:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible(timeout=2000):
                        campo = el
                        break
                except Exception:
                    continue

            if not campo:
                html = await page.content()
                with open("/tmp/simit_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)
                raise RuntimeError("No se encontro el campo de busqueda del SIMIT")

            # Ingresar cedula y buscar
            await campo.click()
            await campo.fill(cedula)
            await page.wait_for_timeout(500)

            # Click en boton o Enter
            btn = page.locator(
                "button[type='submit'], button:has-text('Consultar'), "
                "button.btn-buscar, [class*='search'] button"
            ).first
            try:
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                else:
                    await campo.press("Enter")
            except Exception:
                await campo.press("Enter")

            # Esperar resultado
            for texto_espera in ["No tienes comparendos", "Resumen", "Comparendos", "comparendo"]:
                try:
                    await page.wait_for_selector(f"text={texto_espera}", timeout=8000)
                    break
                except Exception:
                    continue
            else:
                await page.wait_for_timeout(4000)

            # Parsear resultados
            return await parsear_resultados(page, cedula)

        except Exception as e:
            return {"success": False, "cedula": cedula, "error": str(e)}
        finally:
            await browser.close()


async def parsear_resultados(page, cedula: str) -> dict:
    # Leer resumen del encabezado
    resumen = await page.evaluate("""() => {
        const texto = document.body.innerText;
        const matchComp  = texto.match(/Comparendos:\\s*(\\d{1,4})(?!\\d)/i);
        const matchMul   = texto.match(/Multas:\\s*(\\d{1,4})(?!\\d)/i);
        const matchTotal = texto.match(/Total[^$\\n]{0,20}\\$\\s*([\\d.,]+)/i);
        const total_str  = matchTotal ? matchTotal[1].replace(/[.,]/g, '') : '0';
        return {
            comparendos: matchComp  ? parseInt(matchComp[1])  : 0,
            multas:      matchMul   ? parseInt(matchMul[1])   : 0,
            valor_total: parseInt(total_str) || 0,
        };
    }""")

    # Leer tabla de multas
    filas = await page.evaluate("""() => {
        const tablas = document.querySelectorAll('table');
        for (const tabla of tablas) {
            const headers = Array.from(tabla.querySelectorAll('th'))
                .map(th => th.innerText.trim().toLowerCase());
            if (headers.some(h => h.includes('tipo') || h.includes('infracci') || h.includes('comparendo'))) {
                return Array.from(tabla.querySelectorAll('tbody tr'))
                    .map(fila => Array.from(fila.querySelectorAll('td')).map(td => td.innerText.trim()))
                    .filter(f => f.length >= 2);
            }
        }
        return [];
    }""")

    multas = []
    for celdas in filas:
        multas.append({
            "numero":     celdas[0] if len(celdas) > 0 else None,
            "placa":      celdas[2] if len(celdas) > 2 else None,
            "secretaria": celdas[3] if len(celdas) > 3 else None,
            "infraccion": celdas[4] if len(celdas) > 4 else None,
            "estado":     celdas[5] if len(celdas) > 5 else None,
            "valor":      parsear_valor(celdas[6] if len(celdas) > 6 else "0"),
        })

    total_pendientes = resumen["comparendos"] + resumen["multas"]
    # Usar valor del resumen siempre que exista — es mas confiable que la tabla
    valor_total = resumen["valor_total"]

    if multas:
        pendientes = [m for m in multas if "PENDIENTE" in (m.get("estado") or "").upper()]
        tiene_multas = len(pendientes) > 0 or total_pendientes > 0
        # Si la tabla tiene valores usar esos, sino usar el resumen
        valor_tabla = sum(m.get("valor", 0) for m in multas)
        valor_total = valor_tabla if valor_tabla > 0 else valor_total
    elif total_pendientes > 0:
        tiene_multas = True
    else:
        tiene_multas = False

    return {
        "success":          True,
        "cedula":           cedula,
        "tiene_multas":     tiene_multas,
        "total_pendientes": total_pendientes if tiene_multas else 0,
        "valor_total":      valor_total if tiene_multas else 0,
        "multas":           multas,
    }


def parsear_valor(texto: str) -> float:
    try:
        return float(texto.replace("$", "").replace(".", "").replace(",", "").strip())
    except Exception:
        return 0.0


if __name__ == "__main__":
    cedula_arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not cedula_arg or not cedula_arg.isdigit():
        print(json.dumps({"success": False, "error": "Uso: python simit_validator.py <cedula>"}))
        sys.exit(1)

    resultado = asyncio.run(consultar_simit(cedula_arg))
    resultado["timestamp"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
