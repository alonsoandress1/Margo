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

FORMATO DEL BODY (no es JSON, es una particularidad de esta app): el
codigo fuente arma el body como un query-string con un "?" al inicio,
ej. "?operatorCode=123&password=abc&language=en" (via
encodeURIComponent + join("&")), y lo manda como texto plano en el
POST -- no como application/json. Se replica exactamente esa forma
aca porque el servidor la exige asi (confirmado: con JSON devolvia
"InvalidUsercodeOrPassword" aun con credenciales correctas que SI
funcionan en el login normal del navegador).
"""
import json as _json
import urllib.error
import urllib.parse
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
        cuerpo = "?" + urllib.parse.urlencode(body)
        req = urllib.request.Request(
            f"{self.api_url}{path}",
            data=cuerpo.encode("utf-8"),
            headers={"Content-Type": "text/plain;charset=UTF-8"},
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


def construir_parametros(formulario: dict, overrides: dict) -> list[dict]:
    """Arma la lista plana [{controlName, value}, ...] que espera
    ejecutar_reporte(), a partir del formulario de parametros (tal cual lo
    devuelve formulario_de_parametros()) y overrides puntuales
    {controlName: valor}. Replica la logica de handleFormSubmit() de la app:

    - Grupos de radio buttons (GroupBox con hijos DbRadioButton): se manda
      un solo {controlName: <boton seleccionado>, value: true} -- el
      seleccionado es el que este en overrides, o si ninguno del grupo esta
      en overrides, el que ya viniera con value=true por defecto.
    - Checklists (DbCheckedListBox): se manda {controlName, value: "id1,id2"}
      -- los ids marcados vienen de overrides[nombre] (lista de ids) o, si
      no hay override, de los items que ya vinieran checked=true.
    - El resto de los controles con nombre: se manda tal cual, con el value
      de overrides si esta, si no el value que ya traia el formulario.
    - Controles sin nombre (labels, etc.) se ignoran.
    """
    parametros: list[dict] = []

    def procesar(control: dict):
        tipo = control.get("type")
        nombre = control.get("name")

        if tipo == "GroupBox":
            hijos = control.get("controls") or []
            radios = [c for c in hijos if c.get("type") == "DbRadioButton"]
            if radios:
                nombres_grupo = [r["name"] for r in radios]
                hay_override = any(n in overrides for n in nombres_grupo)
                if hay_override:
                    seleccionado = next((r for r in radios if overrides.get(r["name"])), radios[0])
                else:
                    seleccionado = next((r for r in radios if r.get("value")), radios[0])
                parametros.append({"controlName": seleccionado["name"], "value": True})
            else:
                for hijo in hijos:
                    procesar(hijo)
            return

        if tipo == "DbCheckedListBox":
            items = control.get("checkedListBoxItems") or []
            if nombre in overrides:
                ids_marcados = [str(v) for v in overrides[nombre]]
            else:
                ids_marcados = [str(it["id"]) for it in items if it.get("checked")]
            parametros.append({"controlName": nombre, "value": ",".join(ids_marcados)})
            return

        if not nombre:
            return  # labels y otros controles decorativos sin name

        valor = overrides[nombre] if nombre in overrides else control.get("value")
        parametros.append({"controlName": nombre, "value": valor})

    for c in formulario.get("controls", []):
        procesar(c)
    return parametros


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
        respuesta = session.listar_reportes()
    except Exception as e:
        print(f"✗ Error al listar reportes: {e}")
        raise SystemExit(1)

    print(f"\n✓ Respuesta cruda (para entender la forma exacta):\n")
    print(_json.dumps(respuesta, indent=2, ensure_ascii=False) if not isinstance(respuesta, str) else respuesta)

    if isinstance(respuesta, dict) and "error" in respuesta and len(respuesta) == 1:
        print(f"\n✗ El servidor rechazó las credenciales: {respuesta['error']}")
        print("Verifica el usuario/operatorCode y la contraseña -- puede que el operatorCode no sea tu email de login,")
        print("sino un código de operador distinto (revisa con quien administra el POS si no estás seguro).")
        raise SystemExit(1)

    # La respuesta puede venir en varias formas segun la version del
    # servidor -- se intenta encontrar la lista real de reportes sin asumir
    # una unica forma fija.
    reportes = None
    if isinstance(respuesta, list) and respuesta and isinstance(respuesta[0], dict):
        reportes = respuesta
    elif isinstance(respuesta, list) and respuesta and isinstance(respuesta[0], str):
        try:
            reportes = _json.loads(respuesta[0])
        except ValueError:
            pass
    elif isinstance(respuesta, dict):
        for v in respuesta.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                reportes = v
                break
            if isinstance(v, str):
                try:
                    posible = _json.loads(v)
                    if isinstance(posible, list) and posible and isinstance(posible[0], dict):
                        reportes = posible
                        break
                except ValueError:
                    pass

    if reportes is None:
        print("\n✗ No se pudo interpretar la forma de la respuesta automaticamente.")
        print("Copia y pega la 'Respuesta cruda' de arriba en el chat (no tiene tu contraseña) y ajustamos el parseo.")
        raise SystemExit(1)

    print(f"\n✓ {len(reportes)} reportes disponibles (interpretados):\n")
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

    salida = "tcpos_formulario.json"
    with open(salida, "w", encoding="utf-8") as f:
        _json.dump(formulario, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Formulario guardado en {salida} (en esta misma carpeta) -- es muy grande para pegarlo en el chat.")

    intentar = input("\n¿Intentar generar el reporte de AYER para Margo Isidora, Group D? (s/n): ").strip().lower()
    if intentar == "s":
        from datetime import date, timedelta
        ayer = (date.today() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        overrides = {
            "edDateFrom": ayer, "edDateTo": ayer,
            "edTimeFrom": 0, "edTimeTo": 1439,
            "rbCalendarDate": True,
            "clbShops": [13],  # 1001 Margo Isidora
            "rbGroupD": True,
        }
        parametros = construir_parametros(formulario, overrides)
        print("\nParámetros armados:")
        print(_json.dumps(parametros, indent=2, ensure_ascii=False))

        print("\nEjecutando el reporte...")
        try:
            resultado = session.ejecutar_reporte(match["formName"], match["assemblyName"], parametros)
        except Exception as e:
            print(f"✗ Error al ejecutar el reporte: {e}")
            raise SystemExit(1)

        salida2 = "tcpos_ejecutar_resultado.json"
        with open(salida2, "w", encoding="utf-8") as f:
            _json.dump(resultado, f, indent=2, ensure_ascii=False) if not isinstance(resultado, str) else f.write(resultado)
        print(f"\n✓ Respuesta guardada en {salida2} -- avisa que ya está listo.")

    input("\nPresiona Enter para cerrar...")
