"""
DIAGNOSTICO - Herramienta de Diagnóstico de Hardware
Punto de entrada principal
"""

import sys

from ui.menu import Menu


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    app = Menu()
    app.run()
