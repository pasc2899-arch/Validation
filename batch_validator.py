"""
Batch Validator - Google Sheets
=================================
Lee cedulas de la hoja "Masivo" y escribe resultados de RUNT + SIMIT.

Columnas entrada:  A=Nombre, B=Telefono, C=Cedula
Columnas salida:   D=nombre_runt, E=coincidencia_nombre, F=licencia_vigente,
                   G=licencia_entidad, H=licencia_fecha,
                   I=simit_multas, J=simit_valor, K=estado_final

REQUISITOS:
    pip install gspread google-auth

VARIABLES DE ENTORNO:
    GOOGLE_CREDENTIALS_JSON  = contenido del JSON de cuenta de servicio
    SHEET_ID                 = 11Fq1rs1q0chCo8HDDhH0cJIrY5Zc2v93HuDxAPhkxLc
"""

import os
import json
import asyncio
import sys
from datetime import datetime, timezone

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print(json.dumps({"error": "Instala: pip install gspread google-auth"}))
    sys.exit(1)

# Importar los validadores existentes
sys.path.insert(0, os.path.dirname(__file__))
from runt_license_validator import validar_licencia
from simit_validator import consultar_simit

SHEET_ID   = os.environ.get("SHEET_ID", "11Fq1rs1q0chCo8HDDhH0cJIrY5Zc2v93HuDxAPhkxLc")
SHEET_NAME = "Masivo"
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON no configurada")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


def calcular_coincidencia(nombre_digitado: str, nombre_runt: str) -> int:
    nd = nombre_digitado.upper().strip()
    nr = nombre_runt.upper().strip()
    palabras = [p for p in nd.split() if len(p) > 1]
    if not palabras:
        return 0
    coincidencias = sum(1 for p in palabras if p in nr)
    return round((coincidencias / len(palabras)) * 100)


async def procesar_cedula(nombre: str, cedula: str) -> dict:
    print(f"  Procesando: {nombre} - {cedula}", flush=True)

    runt_task  = asyncio.create_task(validar_licencia(cedula))
    simit_task = asyncio.create_task(consultar_simit(cedula))

    runt  = await runt_task
    simit = await simit_task

    # Nombre RUNT
    nombre_runt = runt.get("conductor", {}).get("nombre", "") if runt.get("success") else ""

    # Coincidencia nombre
    coincidencia = calcular_coincidencia(nombre, nombre_runt) if nombre_runt else 0

    # Licencia
    licencia_vigente  = runt.get("licencia_vigente", False) if runt.get("success") else False
    licencia_activa   = runt.get("licencia_activa") or {}
    licencia_entidad  = licencia_activa.get("entidad_expide", "") if licencia_activa else ""
    licencia_fecha    = licencia_activa.get("fecha_expedicion", "") if licencia_activa else ""

    # SIMIT
    tiene_multas      = simit.get("tiene_multas", False) if simit.get("success") else False
    total_pendientes  = simit.get("total_pendientes", 0)
    valor_total       = simit.get("valor_total", 0)

    # Estado final
    if not runt.get("success"):
        estado = "ERROR_RUNT"
    elif not licencia_vigente:
        estado = "RECHAZADO_LICENCIA"
    elif tiene_multas:
        estado = "RECHAZADO_MULTAS"
    elif coincidencia < 60:
        estado = "RECHAZADO_NOMBRE"
    else:
        estado = "APROBADO"

    return {
        "nombre_runt":        nombre_runt,
        "coincidencia":       f"{coincidencia}%",
        "licencia_vigente":   "SI" if licencia_vigente else "NO",
        "licencia_entidad":   licencia_entidad,
        "licencia_fecha":     licencia_fecha,
        "simit_multas":       total_pendientes,
        "simit_valor":        f"${valor_total:,.0f}" if valor_total else "$0",
        "estado_final":       estado,
    }


async def run_batch():
    print("Conectando a Google Sheets...", flush=True)
    sheet = get_sheet()
    rows  = sheet.get_all_values()

    if not rows:
        print("Hoja vacia", flush=True)
        return {"procesadas": 0}

    # Detectar fila de encabezado
    start_row = 1
    if rows[0][0].lower() in ("nombre", "name"):
        start_row = 1  # encabezado en fila 1, datos desde fila 2

    procesadas = 0
    errores    = 0

    for i, row in enumerate(rows):
        fila_sheet = i + 1  # 1-indexed

        # Saltar encabezado
        if i == 0 and row[0].lower() in ("nombre", "name"):
            continue

        # Saltar filas vacias
        nombre = row[0].strip() if len(row) > 0 else ""
        cedula = row[2].strip() if len(row) > 2 else ""

        if not cedula or not cedula.replace(" ", "").isdigit():
            continue

        cedula = cedula.replace(" ", "")

        # Saltar si ya fue procesada (columna K tiene valor)
        if len(row) > 10 and row[10].strip():
            print(f"  Fila {fila_sheet} ya procesada, saltando...", flush=True)
            continue

        try:
            resultado = await procesar_cedula(nombre, cedula)

            # Escribir columnas D a K
            sheet.update(
                range_name=f"D{fila_sheet}:K{fila_sheet}",
                values=[[
                    resultado["nombre_runt"],
                    resultado["coincidencia"],
                    resultado["licencia_vigente"],
                    resultado["licencia_entidad"],
                    resultado["licencia_fecha"],
                    resultado["simit_multas"],
                    resultado["simit_valor"],
                    resultado["estado_final"],
                ]]
            )
            print(f"  Fila {fila_sheet} -> {resultado['estado_final']}", flush=True)
            procesadas += 1

            # Pausa entre requests para no sobrecargar
            await asyncio.sleep(3)

        except Exception as e:
            print(f"  Error fila {fila_sheet}: {e}", flush=True)
            sheet.update(
                range_name=f"K{fila_sheet}",
                values=[[f"ERROR: {str(e)[:50]}"]]
            )
            errores += 1

    return {"procesadas": procesadas, "errores": errores}


if __name__ == "__main__":
    resultado = asyncio.run(run_batch())
    print(json.dumps(resultado))
