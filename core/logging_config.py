import logging
import os
import sys


def configurar_logging() -> logging.Logger:
    logger = logging.getLogger("hardware_diagnostico")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    if getattr(sys, "frozen", False):
        raiz = os.path.dirname(sys.executable)
    else:
        raiz = os.path.dirname(os.path.dirname(__file__))
    directorio = os.path.join(raiz, "logs")
    os.makedirs(directorio, exist_ok=True)

    manejador = logging.FileHandler(
        os.path.join(directorio, "hardware_diagnostico.log"),
        encoding="utf-8",
    )
    manejador.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(manejador)
    return logger
