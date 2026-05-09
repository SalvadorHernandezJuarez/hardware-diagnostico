"""
modules/gpu.py - Detección e información de GPU
Soporta NVIDIA (via GPUtil), AMD/Intel (via wmi) y fallback básico
"""

from modules.base import ModuloBase

try:
    import GPUtil
    GPUTIL_DISPONIBLE = True
except ImportError:
    GPUTIL_DISPONIBLE = False

try:
    import wmi
    WMI_DISPONIBLE = True
except ImportError:
    WMI_DISPONIBLE = False


class GPUInfo(ModuloBase):
    nombre = "GPU"

    def obtener(self) -> dict:
        datos = {"gpus": []}

        # Primero intentar GPUtil (mejor para NVIDIA)
        if GPUTIL_DISPONIBLE:
            try:
                gpus = GPUtil.getGPUs()
                for gpu in gpus:
                    datos["gpus"].append({
                        "Nombre": gpu.name,
                        "VRAM Total": f"{gpu.memoryTotal} MB",
                        "VRAM Usada": f"{gpu.memoryUsed} MB",
                        "VRAM Libre": f"{gpu.memoryFree} MB",
                        "Carga GPU": f"{gpu.load * 100:.1f} %",
                        "Temperatura": f"{gpu.temperature} °C",
                        "Driver": gpu.driver,
                        "Fuente": "GPUtil (NVIDIA)",
                    })
            except Exception:
                pass

        # Fallback con WMI (AMD, Intel, cualquier GPU)
        if not datos["gpus"] and WMI_DISPONIBLE:
            try:
                c = wmi.WMI()
                for gpu in c.Win32_VideoController():
                    vram_gb = int(gpu.AdapterRAM) / (1024**2) if gpu.AdapterRAM else 0
                    datos["gpus"].append({
                        "Nombre": gpu.Name,
                        "VRAM": f"{vram_gb:.0f} MB",
                        "Resolución actual": f"{gpu.CurrentHorizontalResolution}x{gpu.CurrentVerticalResolution}",
                        "Bits de color": gpu.CurrentBitsPerPixel,
                        "Driver versión": gpu.DriverVersion,
                        "Estado": gpu.Status,
                        "Fuente": "WMI",
                    })
            except Exception:
                pass

        if not datos["gpus"]:
            datos["estado"] = "No se pudo detectar GPU"

        return datos

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("🎮 TARJETA GRÁFICA (GPU)")

        if "estado" in datos:
            self._fila("Estado", datos["estado"])
            return

        for i, gpu in enumerate(datos["gpus"], 1):
            if len(datos["gpus"]) > 1:
                print(f"\n  GPU #{i}")
            for k, v in gpu.items():
                if not profesional and k in ("Driver", "Driver versión", "Fuente", "Bits de color"):
                    continue
                self._fila(k, v)
            print(f"  {'─' * 46}")
