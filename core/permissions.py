import logging
from typing import Callable

from core.actions import ActionRisk


logger = logging.getLogger("hardware_diagnostico")


def solicitar_autorizacion(
    riesgo: ActionRisk,
    descripcion: str,
    modo_profesional: bool = False,
    input_func: Callable[[str], str] = input,
) -> bool:
    """Autoriza acciones futuras según su riesgo; no ejecuta la acción."""
    if riesgo is ActionRisk.SAFE:
        return True
    if riesgo is ActionRisk.PROFESSIONAL and not modo_profesional:
        logger.warning(
            "Acción profesional bloqueada | modo=normal | descripción=%s",
            descripcion,
        )
        print("Esta acción solo se permite en Modo Profesional.")
        return False

    if riesgo is ActionRisk.PROFESSIONAL:
        respuesta = input_func(
            f"{riesgo.display} {descripcion}\n"
            "Escribe CONFIRMAR para autorizar: "
        ).strip()
        autorizada = respuesta == "CONFIRMAR"
    else:
        respuesta = input_func(
            f"{riesgo.display} {descripcion}\n"
            "¿Deseas continuar? (s/n): "
        ).strip().lower()
        autorizada = respuesta == "s"

    logger.info(
        "Autorización de acción %s | riesgo=%s | modo=%s | descripción=%s",
        "concedida" if autorizada else "rechazada",
        riesgo.value,
        "profesional" if modo_profesional else "normal",
        descripcion,
    )
    return autorizada


def registrar_accion(descripcion: str, riesgo: ActionRisk, modo_profesional: bool):
    """Registra una acción después de que su operación haya terminado."""
    logger.info(
        "Acción ejecutada | riesgo=%s | modo=%s | descripción=%s",
        riesgo.value,
        "profesional" if modo_profesional else "normal",
        descripcion,
    )
