"""
modules/cpu.py - Información del procesador
"""

import psutil
from modules.base import ModuloBase

try:
    import wmi
    WMI_DISPONIBLE = True
except ImportError:
    WMI_DISPONIBLE = False


class CPUInfo(ModuloBase):
    nombre = "CPU"

    def obtener(self) -> dict:
        datos = {
            "Uso actual": f"{psutil.cpu_percent(interval=1)} %",
            "Núcleos físicos": psutil.cpu_count(logical=False),
            "Hilos (lógicos)": psutil.cpu_count(logical=True),
        }

        freq = psutil.cpu_freq()
        if freq:
            datos["Frecuencia actual"] = f"{freq.current:.0f} MHz"
            datos["Frecuencia máxima"] = f"{freq.max:.0f} MHz"

        if WMI_DISPONIBLE:
            try:
                c = wmi.WMI()
                for cpu in c.Win32_Processor():
                    datos["Nombre"] = cpu.Name.strip()
                    datos["Fabricante"] = cpu.Manufacturer
                    datos["Arquitectura"] = str(cpu.Architecture)
                    datos["Nivel de caché L2 (KB)"] = cpu.L2CacheSize
                    datos["Nivel de caché L3 (KB)"] = cpu.L3CacheSize
                    break
            except Exception:
                pass

        return datos

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("⚡ PROCESADOR")
        campos_basicos = {"Nombre", "Uso actual", "Núcleos físicos", "Hilos (lógicos)", "Frecuencia máxima"}
        for clave, valor in datos.items():
            if not profesional and clave not in campos_basicos:
                continue
            self._fila(clave, valor)
