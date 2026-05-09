"""
modules/disco.py - Información de discos y uso de almacenamiento
Incluye diagnóstico de salud básico via SMART (requiere wmi)
"""

import psutil
import subprocess
from modules.base import ModuloBase

try:
    import wmi
    WMI_DISPONIBLE = True
except ImportError:
    WMI_DISPONIBLE = False


def _salud_smart(modelo: str) -> str:
    """Intenta obtener salud SMART del disco via wmic (solo Windows)."""
    try:
        resultado = subprocess.check_output(
            ["wmic", "diskdrive", "get", "Status"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode(errors="ignore")
        lineas = [l.strip() for l in resultado.splitlines() if l.strip() and l.strip() != "Status"]
        if lineas:
            return lineas[0]
    except Exception:
        pass
    return "No disponible"


class DiscoInfo(ModuloBase):
    nombre = "Discos"

    def obtener(self) -> dict:
        datos = {"discos_fisicos": [], "particiones": []}

        if WMI_DISPONIBLE:
            try:
                c = wmi.WMI()
                for disk in c.Win32_DiskDrive():
                    size_gb = int(disk.Size) / (1024**3) if disk.Size else 0
                    datos["discos_fisicos"].append({
                        "Modelo": disk.Model,
                        "Tamaño": f"{size_gb:.2f} GB",
                        "Interfaz": disk.InterfaceType,
                        "Particiones": disk.Partitions,
                        "Número de serie": disk.SerialNumber,
                        "Estado SMART": _salud_smart(disk.Model),
                    })
            except Exception:
                pass

        for part in psutil.disk_partitions():
            try:
                uso = psutil.disk_usage(part.mountpoint)
                datos["particiones"].append({
                    "Unidad": part.device,
                    "Tipo": part.fstype,
                    "Total": f"{uso.total / (1024**3):.2f} GB",
                    "Usado": f"{uso.used / (1024**3):.2f} GB",
                    "Libre": f"{uso.free / (1024**3):.2f} GB",
                    "Uso": f"{uso.percent} %",
                })
            except Exception:
                pass

        return datos

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("💾 DISCOS")

        if datos["discos_fisicos"]:
            print("\n  [ Discos físicos ]\n")
            for disco in datos["discos_fisicos"]:
                for k, v in disco.items():
                    if not profesional and k in ("Número de serie", "Particiones"):
                        continue
                    self._fila(k, v)
                print(f"  {'─' * 46}")

        print("\n  [ Particiones / Uso ]\n")
        for p in datos["particiones"]:
            for k, v in p.items():
                if not profesional and k == "Tipo":
                    continue
                self._fila(k, v)
            # Barra visual de uso
            pct = float(p["Uso"].replace(" %", ""))
            barra = self._barra_uso(pct)
            print(f"  {'Almacenamiento':<28} {barra}")
            print(f"  {'─' * 46}")

    def _barra_uso(self, porcentaje: float, largo: int = 20) -> str:
        llenos = int(porcentaje / 100 * largo)
        vacios = largo - llenos
        color = "🟥" if porcentaje > 85 else "🟨" if porcentaje > 60 else "🟩"
        return f"[{'█' * llenos}{'░' * vacios}] {porcentaje:.1f}% {color}"
