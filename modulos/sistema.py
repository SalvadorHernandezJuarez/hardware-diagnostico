"""
modules/sistema.py - Información del sistema operativo
"""

import platform
from modules.base import ModuloBase


class SistemaInfo(ModuloBase):
    nombre = "Sistema Operativo"

    def obtener(self) -> dict:
        return {
            "Sistema": platform.system(),
            "Release": platform.release(),
            "Versión": platform.version(),
            "Arquitectura": platform.machine(),
            "Hostname": platform.node(),
            "Python": platform.python_version(),
        }

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("💻 SISTEMA OPERATIVO")
        for clave, valor in datos.items():
            if not profesional and clave in ("Versión", "Hostname", "Python"):
                continue
            self._fila(clave, valor)
