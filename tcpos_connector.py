# -*- coding: utf-8 -*-
"""
tcpos_connector.py — Cliente para el sistema de reportes TCPOS Web Reports
(Margo/Nelí). Sin dependencias externas — stdlib únicamente, mismo criterio
que odoo_connector.py.

Endpoints reales (confirmados leyendo el bundle JS de la app, solo lectura,
sin loguearse):
  POST {API_URL}/webreports-get-reports-list   {operatorCode, password, language}
  POST {API_URL}/webreports-get-input-form     {operatorCode, password, language, reportFormName, reportAssemblyName}
  POST {API_URL}/webreports-execute-report     {operatorCode, password, language, reportFormName, reportAssemblyName, parameters}

IMPORTANTE: este sistema corre en HTTP plano (no HTTPS) y manda usuario y
contraseña en cada request -- no hay endpoint de login separado ni sesión.
Usar credenciales de solo lectura si el POS lo permite.
"""
import json as _json
import urllib.error
import urllib.request
from typing import Optional


class TcposWebReportSession:
    def __init__(self, api_url: str, operator_code: str, password: str,
                 language: str = "en", timeout: int = 30):
        self.api_url = api_url.rstrip("/")
        self.operator_code = operator_code
        self.password = password
        self.language = language
        self.timeout = timeout

    def _post(self, path: str, body: dict):
        req = urllib.request.Request(
            f"{self.api_url}{path}",
            data=_json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"TCPOS devolvió {e.code} en {path}: {detalle}") from e
        try:
            return _json.loads(raw)
        except ValueError:
            return raw

    def listar_reportes(self) -> list[dict]:
        """GET_REPORTS -- lista de reportes disponibles, cada uno con
        displayName/formName/assemblyName."""
        return self._post("/webreports-get-reports-list", {
            "operatorCode": self.operator_code, "password": self.password, "language": self.language,
        })

    def formulario_de_parametros(self, report_form_name: str, report_assembly_name: str) -> dict:
        """GET_INPUT_FORM -- que parametros pide un reporte (fecha, local,
        grupo, etc.) y sus opciones validas."""
        return self._post("/webreports-get-input-form", {
            "operatorCode": self.operator_code, "password": self.password, "language": self.language,
            "reportFormName": report_form_name, "reportAssemblyName": report_assembly_name,
        })

    def ejecutar_reporte(self, report_form_name: str, report_assembly_name: str,
                          parametros: list[dict]) -> dict:
        """EXECUTE_REPORT -- corre el reporte con los parametros ya llenos
        (mismo formato que devuelve formulario_de_parametros, con 'value'
        completado). Retorna la respuesta con la url/referencia del archivo
        generado."""
        return self._post("/webreports-execute-report", {
            "operatorCode": self.operator_code, "password": self.password, "language": self.language,
            "reportFormName": report_form_name, "reportAssemblyName": report_assembly_name,
            "parameters": _json.dumps({"parameters": parametros}),
        })

    def descargar_archivo(self, url: str) -> bytes:
        """Descarga el archivo generado por ejecutar_reporte(). Si la url es
        relativa, se resuelve contra api_url."""
        if url.startswith("/"):
            url = f"{self.api_url}{url}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()


# ── CLI de descubrimiento: solo lectura, no descarga nada todavia ─────────
#
# Uso: python tcpos_connector.py
# Corre esto en tu propia terminal -- las credenciales NO se guardan en
# ningun lado. El objetivo es ver la lista de reportes disponibles y, para
# "Article Analysis" (o el que corresponda), que parametros exactos pide
# (fecha, local, grupo) y con que formato/opciones -- para poder automatizar
# el llenado despues sin adivinar.
if __name__ == "__main__":
    import getpass

    print("Descubrimiento de reportes TCPOS -- las credenciales NO se guardan en ningún lado.\n")
    api_url = input("URL del sistema (ej. http://45.236.165.14:9093): ").strip()
    operator_code = input("Usuario/operatorCode: ").strip()
    password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

    session = TcposWebReportSession(api_url, operator_code, password)

    try:
        reportes = session.listar_reportes()
    except Exception as e:
        print(f"✗ Error al listar reportes: {e}")
        raise SystemExit(1)

    print(f"\n✓ {len(reportes)} reportes disponibles:\n")
    for r in reportes:
        print(f"  - {r.get('displayName')}  (formName={r.get('formName')}, assemblyName={r.get('assemblyName')})")

    objetivo = input("\nNombre EXACTO (displayName) del reporte de ventas por articulo (ej. 'Article Analysis'): ").strip()
    match = next((r for r in reportes if r.get("displayName", "").strip().lower() == objetivo.lower()), None)
    if not match:
        print(f"✗ No se encontró un reporte con displayName='{objetivo}'. Revisa el listado de arriba.")
        raise SystemExit(1)

    print(f"\nPidiendo el formulario de parámetros de '{match['displayName']}'...")
    try:
        formulario = session.formulario_de_parametros(match["formName"], match["assemblyName"])
    except Exception as e:
        print(f"✗ Error al pedir el formulario: {e}")
        raise SystemExit(1)

    print("\n✓ Formulario de parámetros (formato crudo, para diseñar el llenado automático):\n")
    print(_json.dumps(formulario, indent=2, ensure_ascii=False))

    print("\n\nCopia y pega TODO lo de arriba (el JSON del formulario) de vuelta en el chat -- no contiene tu contraseña.")
    input("\nPresiona Enter para cerrar...")
