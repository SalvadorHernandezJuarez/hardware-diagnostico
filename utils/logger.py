"""
utils/logger.py - Sistema de logs para guardar diagnósticos anteriores
"""

import os
import json
from datetime import datetime


RUTA_LOGS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


class Logger:
    def __init__(self):
        os.makedirs(RUTA_LOGS, exist_ok=True)
        self._sesion_archivo = None

    def iniciar_sesion(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"diagnostico_{timestamp}.json"
        self._sesion_archivo = os.path.join(RUTA_LOGS, nombre)
        print(f"\n  📝 Log iniciado: {nombre}")

    def registrar(self, nombre_modulo: str, datos: dict):
        if not self._sesion_archivo:
            return
        try:
            # Cargar log existente si ya tiene datos
            if os.path.exists(self._sesion_archivo):
                with open(self._sesion_archivo, "r", encoding="utf-8") as f:
                    log = json.load(f)
            else:
                log = {"fecha": datetime.now().isoformat(), "modulos": {}}

            log["modulos"][nombre_modulo] = datos

            with open(self._sesion_archivo, "w", encoding="utf-8") as f:
                json.dump(log, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"  ⚠️  Error al guardar log: {e}")

    def mostrar_logs(self):
        archivos = sorted(
            [f for f in os.listdir(RUTA_LOGS) if f.endswith(".json")],
            reverse=True,
        )

        print("\n" + "=" * 50)
        print("  📁 LOGS ANTERIORES")
        print("=" * 50)

        if not archivos:
            print("  No hay logs guardados aún.")
            input("\n  Presiona ENTER para volver...")
            return

        for i, archivo in enumerate(archivos[:10], 1):
            print(f"  {i}. {archivo}")

        print("\n  [0] Volver")
        seleccion = input("\n  Ver log número: ").strip()

        if seleccion == "0" or not seleccion.isdigit():
            return

        idx = int(seleccion) - 1
        if 0 <= idx < len(archivos):
            ruta = os.path.join(RUTA_LOGS, archivos[idx])
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    log = json.load(f)
                print(f"\n  Fecha: {log.get('fecha', 'Desconocida')}\n")
                for modulo, datos in log.get("modulos", {}).items():
                    print(f"\n  === {modulo} ===")
                    print(f"  {json.dumps(datos, indent=4, ensure_ascii=False, default=str)}")
            except Exception as e:
                print(f"  ⚠️  Error leyendo log: {e}")

        input("\n  Presiona ENTER para volver...")
