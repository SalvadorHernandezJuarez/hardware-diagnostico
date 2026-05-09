"""
modules/ram.py - Información de memoria RAM
"""

import psutil
from modules.base import ModuloBase

try:
    import wmi
    WMI_DISPONIBLE = True
except ImportError:
    WMI_DISPONIBLE = False

TIPOS_RAM = {
    0: "Desconocido", 1: "Otro", 2: "DRAM", 3: "SDRAM",
    4: "SRAM", 5: "WRAM", 6: "RDRAM", 7: "DRAM", 8: "Reserved",
    11: "SDRAM", 17: "SDRAM", 18: "SDRAM", 19: "DDR", 20: "DDR2",
    21: "DDR2 FB-DIMM", 22: "DDR2 FB-DIMM", 24: "DDR3", 26: "DDR4",
    34: "DDR5",
}


class RAMInfo(ModuloBase):
    nombre = "RAM"

    def obtener(self) -> dict:
        mem = psutil.virtual_memory()
        datos = {
            "Total": f"{mem.total / (1024**3):.2f} GB",
            "Disponible": f"{mem.available / (1024**3):.2f} GB",
            "Usado": f"{mem.used / (1024**3):.2f} GB",
            "Porcentaje de uso": f"{mem.percent} %",
            "slots": [],
        }

        if WMI_DISPONIBLE:
            try:
                c = wmi.WMI()
                for stick in c.Win32_PhysicalMemory():
                    slot_data = {
                        "Capacidad": f"{int(stick.Capacity) / (1024**3):.2f} GB",
                        "Tipo": TIPOS_RAM.get(stick.MemoryType, f"Código {stick.MemoryType}"),
                        "Velocidad": f"{stick.Speed} MHz",
                        "Fabricante": stick.Manufacturer,
                        "Slot": stick.DeviceLocator,
                    }
                    datos["slots"].append(slot_data)
            except Exception:
                pass

        return datos

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("🧠 MEMORIA RAM")
        for clave, valor in datos.items():
            if clave == "slots":
                continue
            self._fila(clave, valor)

        if datos.get("slots"):
            print(f"\n  {'— Módulos instalados —':^46}")
            for i, slot in enumerate(datos["slots"], 1):
                print(f"\n  Módulo #{i}")
                for k, v in slot.items():
                    if not profesional and k in ("Fabricante", "Slot"):
                        continue
                    self._fila(f"  {k}", v)
