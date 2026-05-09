"""
modules/temperatura.py - Temperaturas del sistema
"""

import psutil
from modules.base import ModuloBase


class TemperaturaInfo(ModuloBase):
    nombre = "Temperatura"

    def obtener(self) -> dict:
        datos = {}
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for sensor, lecturas in temps.items():
                    for entrada in lecturas:
                        clave = f"{sensor} / {entrada.label}" if entrada.label else sensor
                        datos[clave] = {
                            "actual": entrada.current,
                            "alta": entrada.high,
                            "critica": entrada.critical,
                        }
        except Exception:
            pass
        return datos if datos else {"estado": "No disponible en este sistema"}

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("🌡️  TEMPERATURA")

        if "estado" in datos:
            self._fila("Estado", datos["estado"])
            return

        for sensor, valores in datos.items():
            actual = valores["actual"]
            alta = valores.get("alta") or 85
            icono = "🔴" if actual >= alta else "🟡" if actual >= alta * 0.8 else "🟢"
            linea = f"{actual}°C  {icono}"
            if profesional and valores.get("alta"):
                linea += f"  (alta: {valores['alta']}°C  crítica: {valores['critica']}°C)"
            self._fila(sensor[:30], linea)
