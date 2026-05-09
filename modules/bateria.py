"""
modules/bateria.py - Estado de la batería
"""

import psutil
from modules.base import ModuloBase


class BateriaInfo(ModuloBase):
    nombre = "Batería"

    def obtener(self) -> dict:
        battery = psutil.sensors_battery()
        if not battery:
            return {"estado": "No detectada (posiblemente PC de escritorio)"}

        tiempo = "Calculando..." if battery.power_plugged else self._formato_tiempo(battery.secsleft)

        return {
            "Porcentaje": f"{battery.percent:.1f} %",
            "Conectada a corriente": "Sí" if battery.power_plugged else "No",
            "Tiempo restante estimado": tiempo,
            "Estado": self._nivel(battery.percent),
        }

    def _nivel(self, pct: float) -> str:
        if pct > 75:
            return "🟢 Bueno"
        elif pct > 40:
            return "🟡 Moderado"
        elif pct > 15:
            return "🟠 Bajo"
        return "🔴 Crítico"

    def _formato_tiempo(self, segundos: int) -> str:
        if segundos < 0:
            return "Desconocido"
        h = segundos // 3600
        m = (segundos % 3600) // 60
        return f"{h}h {m}m"

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("🔋 BATERÍA")
        for clave, valor in datos.items():
            self._fila(clave, valor)
