"""
DIAGNOSTICO - Herramienta de Diagnóstico de Hardware
Punto de entrada principal
"""

import sys

from core.logging_config import configurar_logging
from ui.menu import Menu


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logger = configurar_logging()
    logger.info("Aplicación iniciada")
    try:
        Menu().run()
    except KeyboardInterrupt:
        logger.info("Aplicación interrumpida por el usuario")
        print("\nAplicación finalizada.")
    except Exception as error:
        logger.exception("Error no controlado durante la ejecución")
        print(f"\nOcurrió un error: {error}")
        print("Consulta logs/hardware_diagnostico.log para más información.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
