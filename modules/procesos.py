import psutil
import logging

from modules.base import ModuloBase


logger = logging.getLogger("hardware_diagnostico")


class ProcesosInfo(ModuloBase):
    nombre = "Procesos"

    def obtener(self) -> dict:
        procesos = []
        for proceso in psutil.process_iter(
            attrs=("pid", "name", "memory_percent", "status")
        ):
            try:
                info = proceso.info
                procesos.append(
                    {
                        "PID": info["pid"],
                        "Nombre": info["name"] or "Desconocido",
                        "Memoria (%)": round(info["memory_percent"] or 0, 2),
                        "Estado": info["status"] or "Desconocido",
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        procesos.sort(key=lambda proceso: proceso["Memoria (%)"], reverse=True)
        return {"procesos": procesos[:10]}

    @staticmethod
    def obtener_detalle_memoria(limite: int = 5) -> dict:
        procesos = []
        for proceso in psutil.process_iter(attrs=("pid", "name", "memory_info")):
            try:
                info = proceso.info
                memory_info = info.get("memory_info")
                rss = memory_info.rss if memory_info else 0
                if rss <= 0:
                    continue
                procesos.append(
                    {
                        "name": info.get("name") or "Desconocido",
                        "rss_bytes": rss,
                        "rss_mb": round(rss / (1024 ** 2), 1),
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (OSError, RuntimeError):
                logger.warning(
                    "No se pudo consultar memoria de un proceso", exc_info=True
                )
        procesos.sort(key=lambda proceso: proceso["rss_bytes"], reverse=True)
        return {"top_memory": procesos[:max(1, limite)]}

    def mostrar(self, datos: dict, profesional: bool = False):
        self._seccion("PROCESOS CON MAYOR USO DE MEMORIA")
        for proceso in datos["procesos"]:
            print(
                f"  PID {proceso['PID']:<7} {proceso['Memoria (%)']:>6.2f}%  "
                f"{proceso['Nombre']} [{proceso['Estado']}]"
            )
        if not datos["procesos"]:
            self._fila("Estado", "No hay procesos disponibles")
