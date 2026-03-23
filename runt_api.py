"""
API Principal - SIMIT + RUNT
=============================
Expone ambos validadores como endpoints HTTP para n8n.

ENDPOINTS:
    GET  /health
    POST /validar/runt   { "cedula": "1014306477" }
    POST /validar/simit  { "cedula": "1014306477" }
    POST /validar/todo   { "cedula": "1014306477" }  <- SIMIT + RUNT juntos
"""

from flask import Flask, request, jsonify
import subprocess
import json
import os
import sys

app = Flask(__name__)

SCRIPT_RUNT  = os.path.join(os.path.dirname(__file__), "runt_license_validator.py")
SCRIPT_SIMIT = os.path.join(os.path.dirname(__file__), "simit_validator.py")
PYTHON_BIN   = sys.executable
API_TOKEN    = os.environ.get("RUNT_API_TOKEN", "")


def check_token():
    if not API_TOKEN:
        return True
    return request.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"


def run_script(script_path: str, cedula: str) -> dict:
    result = subprocess.run(
        [PYTHON_BIN, script_path, cedula],
        capture_output=True, text=True, timeout=120,
        env={**os.environ},
    )
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(f"Script sin output. stderr: {result.stderr[:300]}")
    return json.loads(stdout)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "runt_script":  os.path.exists(SCRIPT_RUNT),
        "simit_script": os.path.exists(SCRIPT_SIMIT),
    })


@app.route("/validar/runt", methods=["POST"])
def validar_runt():
    if not check_token():
        return jsonify({"error": "No autorizado"}), 401
    cedula = str((request.get_json(force=True, silent=True) or {}).get("cedula", "")).strip()
    if not cedula or not cedula.isdigit():
        return jsonify({"success": False, "error": "cedula invalida"}), 400
    try:
        return jsonify(run_script(SCRIPT_RUNT, cedula))
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/validar/simit", methods=["POST"])
def validar_simit():
    if not check_token():
        return jsonify({"error": "No autorizado"}), 401
    cedula = str((request.get_json(force=True, silent=True) or {}).get("cedula", "")).strip()
    if not cedula or not cedula.isdigit():
        return jsonify({"success": False, "error": "cedula invalida"}), 400
    try:
        return jsonify(run_script(SCRIPT_SIMIT, cedula))
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/validar/todo", methods=["POST"])
def validar_todo():
    if not check_token():
        return jsonify({"error": "No autorizado"}), 401
    cedula = str((request.get_json(force=True, silent=True) or {}).get("cedula", "")).strip()
    if not cedula or not cedula.isdigit():
        return jsonify({"success": False, "error": "cedula invalida"}), 400
    try:
        runt  = run_script(SCRIPT_RUNT,  cedula)
        simit = run_script(SCRIPT_SIMIT, cedula)
        return jsonify({
            "success": True,
            "cedula":  cedula,
            "runt":    runt,
            "simit":   simit,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


batch_status = {"running": False, "procesadas": 0, "errores": 0, "mensaje": ""}

@app.route("/validar/batch", methods=["POST"])
def validar_batch():
    if not check_token():
        return jsonify({"error": "No autorizado"}), 401
    if batch_status["running"]:
        return jsonify({"success": False, "error": "Ya hay un batch corriendo"}), 400
    import threading, asyncio
    from batch_validator import run_batch
    def run():
        batch_status["running"] = True
        batch_status["mensaje"] = "Procesando..."
        try:
            resultado = asyncio.run(run_batch())
            batch_status.update({"procesadas": resultado.get("procesadas", 0),
                                  "errores": resultado.get("errores", 0),
                                  "mensaje": "Completado"})
        except Exception as e:
            batch_status["mensaje"] = f"Error: {str(e)}"
        finally:
            batch_status["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "mensaje": "Batch iniciado en segundo plano. Consulta /validar/batch/status para ver el progreso."})


@app.route("/validar/batch/status", methods=["GET"])
def batch_status_endpoint():
    return jsonify(batch_status)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"API corriendo en http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
