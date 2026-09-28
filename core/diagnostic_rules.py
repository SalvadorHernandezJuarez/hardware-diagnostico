"""Deterministic diagnostic rules over structured hardware data."""

import logging

from core.result import DiagnosticResult
from core.severity import Severity
from core.thresholds import RULE_PRIORITIES, THRESHOLDS


logger = logging.getLogger("hardware_diagnostico")


def _finding(
    code,
    component,
    title,
    severity,
    description,
    evidence,
    current_value=None,
    expected_value=None,
    recommendation="",
    confidence="ALTA",
    source="psutil",
    possible_causes=(),
):
    logger.info("Regla evaluada | componente=%s | regla=%s", component, code)
    logger.info(
        "Hallazgo generado | codigo=%s | componente=%s | severidad=%s",
        code,
        component,
        severity.label,
    )
    return DiagnosticResult(
        code=code,
        component=component,
        title=title,
        severity=severity,
        description=description,
        evidence=evidence,
        current_value=current_value,
        expected_value=expected_value,
        recommendation=recommendation,
        confidence=confidence,
        source=source,
        rule_id=code,
        priority=RULE_PRIORITIES.get(code, 100),
        possible_causes=list(possible_causes),
    )


def _info(code, component, title, description, evidence=None, source="WMI/CIM"):
    return _finding(
        code,
        component,
        title,
        Severity.INFORMATION,
        description,
        evidence or {},
        confidence="MEDIA",
        source=source,
    )


def evaluate_hardware(data):
    """Return findings; missing metrics create information, never a fault."""
    findings = []
    _evaluate_temperatures(data, findings)
    _evaluate_cpu(data.get("cpu") or {}, findings)
    _evaluate_ram(data.get("ram") or {}, findings)
    _evaluate_storage(data.get("storage") or {}, findings)
    _evaluate_gpu(data.get("gpu") or {}, findings)
    _evaluate_battery(data.get("battery") or {}, findings)
    _evaluate_system(data.get("system") or {}, findings)
    return sorted(
        findings,
        key=lambda item: (-int(item.severity), item.priority, item.timestamp),
    )


def _evaluate_cpu(cpu, findings):
    component = "CPU"
    if not cpu:
        findings.append(
            _info("CPU_DATA_UNAVAILABLE", component, "Datos de CPU no disponibles",
                  "No fue posible obtener información del procesador.")
        )
        return

    samples = cpu.get("usage_samples_percent") or []
    valid_samples = [
        float(sample) for sample in samples
        if isinstance(sample, (int, float)) and 0 <= sample <= 100
    ]
    if len(valid_samples) >= THRESHOLDS.cpu_samples:
        mean_usage = sum(valid_samples) / len(valid_samples)
        sustained_count = sum(
            sample >= THRESHOLDS.cpu_sustained_percent for sample in valid_samples
        )
        if (
            sustained_count >= THRESHOLDS.cpu_samples
            and mean_usage >= THRESHOLDS.cpu_sustained_percent
        ):
            findings.append(
                _finding(
                    "CPU_SUSTAINED_HIGH_USAGE",
                    component,
                    "Uso sostenido elevado del procesador",
                    Severity.ALERT,
                    "El procesador permaneció con uso elevado durante la medición.",
                    {
                        "samples_percent": valid_samples,
                        "mean_percent": round(mean_usage, 1),
                        "duration_seconds": cpu.get("usage_sample_duration_seconds"),
                    },
                    round(mean_usage, 1),
                    f"< {THRESHOLDS.cpu_sustained_percent:g}% sostenido",
                    "Revisar los procesos activos y repetir la medición si la carga ya terminó.",
                    possible_causes=(
                        "Aplicaciones con carga sostenida",
                        "Tareas de fondo o actualizaciones",
                    ),
                )
            )
        elif any(sample >= THRESHOLDS.cpu_sustained_percent for sample in valid_samples):
            findings.append(
                _info(
                    "CPU_TRANSIENT_SPIKE",
                    component,
                    "Pico momentáneo de uso del procesador",
                    "Se observó una muestra alta, pero no se mantuvo durante toda la medición.",
                    {"samples_percent": valid_samples, "mean_percent": round(mean_usage, 1)},
                    source="psutil",
                )
            )
        else:
            findings.append(
                _finding(
                    "CPU_USAGE_NORMAL",
                    component,
                    "Uso del procesador dentro del umbral",
                    Severity.NORMAL,
                    "No se detectó uso sostenido elevado durante la medición.",
                    {"samples_percent": valid_samples, "mean_percent": round(mean_usage, 1)},
                    round(mean_usage, 1),
                    f"< {THRESHOLDS.cpu_sustained_percent:g}% sostenido",
                    confidence="ALTA",
                )
            )
    else:
        snapshot = cpu.get("usage_percent")
        findings.append(
            _info(
                "CPU_SUSTAINED_USAGE_UNAVAILABLE",
                component,
                "No se pudo determinar carga sostenida de CPU",
                "La medición sostenida requiere varias muestras válidas.",
                {"snapshot_percent": snapshot, "samples_percent": valid_samples},
                source="psutil",
            )
        )

def _evaluate_ram(ram, findings):
    component = "RAM"
    modules = ram.get("modules") or []
    if modules:
        findings.append(
            _info(
                "RAM_MODULE_CONFIGURATION",
                component,
                "Configuración de módulos de memoria recopilada",
                "Se obtuvo la configuración SMBIOS; no se infieren canales ni capacidad máxima física a partir del número de módulos.",
                {
                    "module_count": len(modules),
                    "slot_count_reported": ram.get("slot_count"),
                    "occupied_slots_reported": ram.get("occupied_slots"),
                    "memory_type": ram.get("memory_type"),
                    "speed_mhz": ram.get("speed_mhz"),
                    "modules": [
                        {
                            "capacity_gb": module.get("capacity_gb"),
                            "memory_type": module.get("memory_type"),
                            "speed_mhz": module.get("speed_mhz"),
                            "device_locator": module.get("device_locator"),
                        }
                        for module in modules
                    ],
                },
                source="WMI/CIM SMBIOS",
            )
        )
    elif ram.get("module_count") == 0:
        findings.append(
            _info(
                "RAM_MODULE_CONFIGURATION_UNAVAILABLE",
                component,
                "Distribución de módulos RAM no disponible",
                "Windows no enumeró módulos físicos de memoria; esto no indica una falla.",
                {"slot_count_reported": ram.get("slot_count")},
                source="WMI/CIM SMBIOS",
            )
        )

    usage = ram.get("usage_percent")
    if not isinstance(usage, (int, float)):
        findings.append(
            _info("RAM_USAGE_UNAVAILABLE", component, "Uso de RAM no disponible",
                  "No fue posible obtener el porcentaje de memoria utilizada.")
        )
        return

    available_gb = ram.get("available_gb")
    if usage > THRESHOLDS.ram_critical_percent:
        code, severity, title, description = (
            "RAM_CRITICAL_USAGE",
            Severity.CRITICAL,
            "Uso crítico de memoria",
            "La memoria disponible está casi agotada.",
        )
        recommendation = "Guardar el trabajo y revisar los procesos con mayor consumo de memoria."
    elif usage >= THRESHOLDS.ram_high_percent:
        code, severity, title, description = (
            "RAM_VERY_HIGH_USAGE",
            Severity.ALERT,
            "Uso muy elevado de memoria",
            "Se detecta un uso muy elevado de memoria; esto no implica por sí solo una falla física.",
        )
        recommendation = "Revisar los procesos que consumen más memoria."
    elif usage >= THRESHOLDS.ram_elevated_percent:
        code, severity, title, description = (
            "RAM_HIGH_USAGE",
            Severity.ALERT,
            "Uso elevado de memoria",
            "Se detecta un uso elevado de memoria; esto no implica por sí solo una falla física.",
        )
        recommendation = "Revisar los procesos que consumen mayor cantidad de memoria."
    elif (
        isinstance(available_gb, (int, float))
        and available_gb < THRESHOLDS.ram_low_available_gb
    ):
        code, severity, title, description = (
            "RAM_LOW_AVAILABLE",
            Severity.ALERT,
            "Memoria disponible reducida",
            "La cantidad de memoria disponible es baja.",
        )
        recommendation = "Revisar los procesos activos y el uso actual de memoria."
    else:
        findings.append(
            _finding(
                "RAM_USAGE_NORMAL",
                component,
                "Uso de memoria dentro del umbral",
                Severity.NORMAL,
                "No se detecta uso elevado ni memoria disponible críticamente baja.",
                {"usage_percent": usage, "available_gb": available_gb},
                usage,
                f"< {THRESHOLDS.ram_elevated_percent:g}%",
            )
        )
        return

    findings.append(
        _finding(
            code,
            component,
            title,
            severity,
            description,
            {
                "usage_percent": usage,
                "available_gb": available_gb,
                "installed_gb": ram.get("installed_gb"),
                "total_gb": ram.get("total_gb"),
            },
            usage,
            f"< {THRESHOLDS.ram_critical_percent:g}%",
            recommendation,
            possible_causes=(
                "Varias aplicaciones abiertas",
                "Procesos con alto consumo",
                "Memoria disponible limitada para la carga actual",
            ),
        )
    )


def _evaluate_storage(storage, findings):
    physical = storage.get("physical_drives") or []
    volumes = storage.get("volumes") or []
    if not physical and not volumes:
        findings.append(
            _info(
                "DISK_DATA_UNAVAILABLE",
                "ALMACENAMIENTO",
                "Almacenamiento no disponible",
                "No fue posible obtener unidades ni volúmenes para analizarlos.",
            )
        )
        return

    storage_issues = sum(
        1
        for finding in findings
        if finding.code.startswith("STORAGE_TEMPERATURE")
        and finding.severity >= Severity.ALERT
    )
    for volume in volumes:
        unit = volume.get("letter") or volume.get("mountpoint") or "Volumen"
        component = f"DISCO {unit}"
        free_gb = volume.get("free_gb")
        total_gb = volume.get("total_gb")
        usage = volume.get("usage_percent")
        if not isinstance(free_gb, (int, float)) or not isinstance(total_gb, (int, float)):
            findings.append(
                _info(
                    "DISK_SPACE_UNAVAILABLE",
                    component,
                    "Espacio libre no disponible",
                    "No fue posible medir la capacidad y el espacio libre de este volumen.",
                    {"volume": unit},
                    source="psutil",
                )
            )
            continue
        free_percent = free_gb * 100 / total_gb if total_gb > 0 else None
        evidence = {
            "volume": unit,
            "capacity_gb": total_gb,
            "used_gb": volume.get("used_gb"),
            "free_gb": free_gb,
            "free_percent": round(free_percent, 1) if free_percent is not None else None,
            "usage_percent": usage,
        }
        if (
            free_gb <= THRESHOLDS.disk_free_critical_gb
            or (
                free_percent is not None
                and free_percent <= THRESHOLDS.disk_free_critical_percent
            )
        ):
            storage_issues += 1
            findings.append(
                _finding(
                    "DISK_CRITICAL_SPACE",
                    component,
                    "Espacio disponible críticamente bajo",
                    Severity.CRITICAL,
                    f"El volumen {unit} tiene muy poco espacio disponible.",
                    evidence,
                    round(free_percent, 1) if free_percent is not None else free_gb,
                    f"> {THRESHOLDS.disk_free_critical_percent:g}% libre y "
                    f"> {THRESHOLDS.disk_free_critical_gb:g} GB",
                    "Revisar archivos grandes y liberar espacio de forma manual.",
                    source="psutil",
                )
            )
        elif (
            free_gb <= THRESHOLDS.disk_free_alert_gb
            or (
                free_percent is not None
                and free_percent <= THRESHOLDS.disk_free_alert_percent
            )
        ):
            storage_issues += 1
            findings.append(
                _finding(
                    "DISK_LOW_SPACE",
                    component,
                    "Espacio disponible reducido",
                    Severity.ALERT,
                    f"El volumen {unit} tiene poco espacio disponible.",
                    evidence,
                    round(free_percent, 1) if free_percent is not None else free_gb,
                    f"> {THRESHOLDS.disk_free_alert_percent:g}% libre y "
                    f"> {THRESHOLDS.disk_free_alert_gb:g} GB",
                    "Revisar archivos grandes y archivos temporales antes de eliminarlos.",
                    source="psutil",
                )
            )

    for index, drive in enumerate(physical, 1):
        name = drive.get("model") or f"Unidad física {index}"
        component = f"DISCO {name}"
        health = drive.get("health")
        if health == "problem":
            storage_issues += 1
            findings.append(
                _finding(
                    "DISK_SMART_FAILURE",
                    component,
                    "El disco reporta una condición de salud problemática",
                    Severity.CRITICAL,
                    "El proveedor de almacenamiento reportó una predicción de fallo.",
                    {"model": name, "health": health},
                    health,
                    "normal",
                    "Respaldar cuanto antes los datos importantes y solicitar evaluación técnica.",
                    source="WMI/CIM SMART",
                )
            )
        elif health == "warning":
            storage_issues += 1
            findings.append(
                _finding(
                    "DISK_SMART_WARNING",
                    component,
                    "El disco reporta una advertencia de salud",
                    Severity.ALERT,
                    "El proveedor de almacenamiento reportó una advertencia; no confirma por sí sola una falla.",
                    {"model": name, "health": health},
                    health,
                    "normal",
                    "Respaldar datos importantes y revisar el estado del disco con la herramienta del fabricante.",
                    source="WMI/CIM SMART",
                )
            )
        elif health is None:
            findings.append(
                _info(
                    "DISK_SMART_UNAVAILABLE",
                    component,
                    "Salud SMART no disponible",
                    "Windows no proporcionó un estado SMART utilizable; esto no se interpreta como fallo.",
                    {"model": name},
                    source="WMI/CIM SMART",
                )
            )

        status = drive.get("status")
        if status and status.casefold() not in ("ok", "unknown", "no disponible"):
            storage_issues += 1
            findings.append(
                _finding(
                    "DISK_DEVICE_STATUS",
                    component,
                    "Estado de dispositivo de almacenamiento reportado por Windows",
                    Severity.ALERT,
                    "Windows reporta un estado distinto de OK para este dispositivo.",
                    {"model": name, "status": status},
                    status,
                    "OK",
                    "Revisar el estado del dispositivo y respaldar información importante.",
                    confidence="MEDIA",
                    source="WMI/CIM",
                )
            )
    if volumes and not physical:
        findings.append(
            _info(
                "DISK_SMART_UNAVAILABLE",
                "ALMACENAMIENTO",
                "Salud SMART no disponible",
                "Se midió espacio de volumen, pero no se obtuvo información de unidades físicas/SMART.",
                {"volume_count": len(volumes)},
                source="WMI/CIM SMART",
            )
        )
    if storage_issues == 0 and (volumes or physical):
        findings.append(
            _finding(
                "STORAGE_NO_REPORTED_PROBLEM",
                "ALMACENAMIENTO",
                "Sin problemas de almacenamiento detectados",
                Severity.NORMAL,
                "No se detectó poco espacio ni una alerta de salud reportada; la disponibilidad de SMART se informa por separado.",
                {
                    "volume_count": len(volumes),
                    "physical_drive_count": len(physical),
                },
                expected_value=(
                    f"más de {THRESHOLDS.disk_free_alert_gb:g} GB y "
                    f"{THRESHOLDS.disk_free_alert_percent:g}% libre"
                ),
                confidence="MEDIA",
                source="psutil y WMI/CIM",
            )
        )


def _evaluate_gpu(gpu, findings):
    cards = gpu.get("cards") or []
    if not cards:
        findings.append(
            _info(
                "GPU_DATA_UNAVAILABLE",
                "GPU",
                "GPU no detectada por el proveedor",
                "No se obtuvieron controladores gráficos mediante Windows; puede ser una limitación del proveedor.",
            )
        )
        return

    issues = sum(
        1
        for finding in findings
        if finding.code.startswith("GPU_TEMPERATURE")
        and finding.severity >= Severity.ALERT
    )
    for index, card in enumerate(cards, 1):
        name = card.get("name") or f"GPU {index}"
        status = card.get("status")
        if status and status.casefold() not in ("ok", "unknown", "no disponible"):
            issues += 1
            findings.append(
                _finding(
                    "GPU_DEVICE_STATUS",
                    f"GPU {name}",
                    "Windows reporta un estado de GPU distinto de OK",
                    Severity.ALERT,
                    "El dispositivo gráfico tiene un estado reportado por Windows que requiere revisión.",
                    {"name": name, "status": status, "driver_version": card.get("driver_version")},
                    status,
                    "OK",
                    "Revisar el controlador y el estado del dispositivo en Windows.",
                    confidence="MEDIA",
                    source="WMI/CIM",
                )
            )

    if issues == 0:
        findings.append(
            _finding(
                "GPU_NO_REPORTED_PROBLEM",
                "GPU",
                "Sin problemas gráficos reportados",
                Severity.NORMAL,
                "El proveedor no reportó estados problemáticos del controlador; la temperatura se evalúa por separado y puede no estar disponible.",
                {"gpu_count": len(cards)},
                confidence="MEDIA",
                source="WMI/CIM/GPUtil",
            )
        )
def _evaluate_battery(battery, findings):
    if not battery.get("detected"):
        findings.append(
            _info(
                "BATTERY_NOT_DETECTED",
                "BATERÍA",
                "No se detectó batería",
                "No se encontró una batería; puede tratarse de un equipo de escritorio.",
                source="psutil/WMI",
            )
        )
        return

    health = battery.get("health_percent")
    if isinstance(health, (int, float)) and 0 <= health <= 100:
        if health < THRESHOLDS.battery_health_critical_wear_percent:
            findings.append(
                _finding(
                    "BATTERY_HEALTH_LOW",
                    "BATERÍA",
                    "Desgaste severo reportado en la batería",
                    Severity.ALERT,
                    "La capacidad máxima actual es reducida respecto de la capacidad de diseño; esto no confirma por sí solo un defecto.",
                    {
                        "design_capacity_mwh": battery.get("design_capacity_mwh"),
                        "full_charge_capacity_mwh": battery.get("full_charge_capacity_mwh"),
                        "health_percent": health,
                        "cycle_count": battery.get("cycle_count"),
                    },
                    health,
                    f"≥ {THRESHOLDS.battery_health_low_percent:g}%",
                    "Considerar revisión de la batería si la autonomía actual es insuficiente.",
                    source="WMI/CIM batería",
                )
            )
        elif health < THRESHOLDS.battery_health_low_percent:
            findings.append(
                _finding(
                    "BATTERY_HEALTH_MODERATE_WEAR",
                    "BATERÍA",
                    "Desgaste moderado reportado en la batería",
                    Severity.ALERT,
                    "La capacidad máxima actual está por debajo del umbral de referencia.",
                    {
                        "design_capacity_mwh": battery.get("design_capacity_mwh"),
                        "full_charge_capacity_mwh": battery.get("full_charge_capacity_mwh"),
                        "health_percent": health,
                        "cycle_count": battery.get("cycle_count"),
                    },
                    health,
                    f"≥ {THRESHOLDS.battery_health_low_percent:g}%",
                    "Considerar revisión si la autonomía actual resulta insuficiente.",
                    source="WMI/CIM batería",
                )
            )
        else:
            findings.append(
                _finding(
                    "BATTERY_HEALTH_NORMAL",
                    "BATERÍA",
                    "Salud reportada de batería dentro del umbral",
                    Severity.NORMAL,
                    "La capacidad máxima actual alcanza el umbral configurado.",
                    {"health_percent": health, "cycle_count": battery.get("cycle_count")},
                    health,
                    f"≥ {THRESHOLDS.battery_health_low_percent:g}%",
                    source="WMI/CIM batería",
                )
            )
    else:
        findings.append(
            _info(
                "BATTERY_HEALTH_UNAVAILABLE",
                "BATERÍA",
                "Salud de batería no disponible",
                "No se obtuvieron ambas capacidades necesarias para calcular la salud.",
                {
                    "design_capacity_mwh": battery.get("design_capacity_mwh"),
                    "full_charge_capacity_mwh": battery.get("full_charge_capacity_mwh"),
                    "cycle_count": battery.get("cycle_count"),
                },
                source="WMI/CIM batería",
            )
        )

    percentage = battery.get("percentage")
    if (
        isinstance(percentage, (int, float))
        and percentage <= THRESHOLDS.battery_low_charge_percent
        and battery.get("power_connected") is False
    ):
        findings.append(
            _finding(
                "BATTERY_LOW_CHARGE",
                "BATERÍA",
                "Carga de batería baja",
                Severity.ALERT,
                "La carga es baja y el equipo no reporta alimentación externa.",
                {"percentage": percentage, "power_connected": False},
                percentage,
                f"> {THRESHOLDS.battery_low_charge_percent:g}% o conectada a corriente",
                "Conectar alimentación para evitar que el equipo se apague al agotarse la carga.",
                source="psutil",
            )
        )


def _evaluate_temperatures(data, findings):
    available = []
    cpu = data.get("cpu") or {}
    if isinstance(cpu.get("temperature_c"), (int, float)):
        available.append("CPU")
    gpu_cards = (data.get("gpu") or {}).get("cards") or []
    if any(isinstance(card.get("temperature_c"), (int, float)) for card in gpu_cards):
        available.append("GPU")
    drives = (data.get("storage") or {}).get("physical_drives") or []
    if any(isinstance(drive.get("temperature_c"), (int, float)) for drive in drives):
        available.append("ALMACENAMIENTO")
    battery = data.get("battery") or {}
    if isinstance(battery.get("temperature_c"), (int, float)):
        available.append("BATERÍA")
        _evaluate_temperature(
            findings,
            "BATTERY_TEMPERATURE",
            "BATERÍA",
            battery["temperature_c"],
            THRESHOLDS.battery_temperature_high_c,
            THRESHOLDS.battery_temperature_critical_c,
            "temperatura de batería",
            "WMI/CIM",
        )
    known = set(available)
    if isinstance(cpu.get("temperature_c"), (int, float)):
        _evaluate_temperature(
            findings,
            "CPU_TEMPERATURE",
            "CPU",
            cpu["temperature_c"],
            THRESHOLDS.cpu_temperature_high_c,
            THRESHOLDS.cpu_temperature_critical_c,
            "temperatura del procesador",
            "WMI/psutil",
        )
    for index, card in enumerate((data.get("gpu") or {}).get("cards") or [], 1):
        value = card.get("temperature_c")
        if isinstance(value, (int, float)):
            _evaluate_temperature(
                findings,
                "GPU_TEMPERATURE",
                f"GPU {card.get('name') or index}",
                value,
                THRESHOLDS.gpu_temperature_high_c,
                THRESHOLDS.gpu_temperature_critical_c,
                "temperatura de la GPU",
                "WMI/GPUtil",
            )
    for index, drive in enumerate(drives, 1):
        value = drive.get("temperature_c")
        if isinstance(value, (int, float)):
            _evaluate_temperature(
                findings,
                "STORAGE_TEMPERATURE",
                f"DISCO {drive.get('model') or index}",
                value,
                THRESHOLDS.storage_temperature_high_c,
                THRESHOLDS.storage_temperature_critical_c,
                "temperatura del almacenamiento",
                "WMI/CIM",
            )
    sensor_data = data.get("temperature_sensors") or {}
    for sensor_name, readings in sensor_data.items():
        if not isinstance(readings, dict):
            continue
        temperature = readings.get("actual")
        if not isinstance(temperature, (int, float)):
            continue
        label = str(sensor_name).casefold()
        if any(token in label for token in ("cpu", "core", "package")):
            component = "CPU"
            thresholds = (
                THRESHOLDS.cpu_temperature_high_c,
                THRESHOLDS.cpu_temperature_critical_c,
            )
            prefix = "CPU_TEMPERATURE"
        elif "gpu" in label:
            component = "GPU"
            thresholds = (
                THRESHOLDS.gpu_temperature_high_c,
                THRESHOLDS.gpu_temperature_critical_c,
            )
            prefix = "GPU_TEMPERATURE"
        elif any(token in label for token in ("disk", "drive", "nvme", "ssd")):
            component = "ALMACENAMIENTO"
            thresholds = (
                THRESHOLDS.storage_temperature_high_c,
                THRESHOLDS.storage_temperature_critical_c,
            )
            prefix = "STORAGE_TEMPERATURE"
        elif "battery" in label:
            component = "BATERÍA"
            thresholds = (
                THRESHOLDS.battery_temperature_high_c,
                THRESHOLDS.battery_temperature_critical_c,
            )
            prefix = "BATTERY_TEMPERATURE"
        else:
            continue
        if component in known:
            continue
        _evaluate_temperature(
            findings,
            prefix,
            f"{component} ({sensor_name})",
            temperature,
            thresholds[0],
            thresholds[1],
            f"temperatura de {component.lower()}",
            "psutil sensores",
        )
        available.append(component)
        known.add(component)

    missing = [
        component
        for component, has_data in (
            ("CPU", isinstance(cpu.get("temperature_c"), (int, float))),
            ("GPU", any(
                isinstance(card.get("temperature_c"), (int, float))
                for card in gpu_cards
            )),
            ("ALMACENAMIENTO", any(
                isinstance(drive.get("temperature_c"), (int, float))
                for drive in drives
            )),
            ("BATERÍA", "BATERÍA" in known),
        )
        if not has_data and component not in known
    ]
    if missing:
        findings.append(
            _info(
                "TEMPERATURE_UNAVAILABLE" if not available else "TEMPERATURE_PARTIAL",
                "TEMPERATURA",
                "Temperaturas no disponibles" if not available else "Temperaturas parciales",
                (
                    "Windows o el proveedor de sensores no expuso lecturas térmicas compatibles; "
                    "no se infiere sobrecalentamiento."
                    if not available
                    else "No hay lecturas térmicas para todos los componentes; los datos ausentes no se interpretan como sobrecalentamiento."
                ),
                {
                    "available_components": available,
                    "components_without_temperature": missing,
                },
                source="psutil/WMI/GPUtil",
            )
        )


def _evaluate_temperature(
    findings,
    prefix,
    component,
    temperature,
    high_threshold,
    critical_threshold,
    label,
    source,
):
    if temperature >= critical_threshold:
        severity = Severity.CRITICAL
        code = f"{prefix}_CRITICAL"
        title = f"Temperatura crítica: {component}"
        description = f"La {label} supera el umbral crítico configurado."
        recommendation = "Reducir la carga, comprobar ventilación y solicitar revisión si la lectura persiste."
    elif temperature >= high_threshold:
        severity = Severity.ALERT
        code = f"{prefix}_HIGH"
        title = f"Temperatura elevada: {component}"
        description = f"La {label} supera el umbral de alerta configurado."
        recommendation = "Comprobar ventilación y volver a medir cuando la carga se estabilice."
    else:
        severity = Severity.NORMAL
        code = f"{prefix}_NORMAL"
        title = f"Temperatura dentro del umbral: {component}"
        description = f"La {label} está por debajo del umbral de alerta."
        recommendation = ""
    findings.append(
        _finding(
            code,
            component,
            title,
            severity,
            description,
            {"temperature_c": temperature, "high_threshold_c": high_threshold,
             "critical_threshold_c": critical_threshold},
            temperature,
            f"< {high_threshold:g} °C",
            recommendation,
            source=source,
            possible_causes=(
                "Carga de trabajo elevada",
                "Ventilación limitada",
            ) if severity >= Severity.ALERT else (),
        )
    )


def _evaluate_system(system, findings):
    if not system:
        findings.append(
            _info(
                "SYSTEM_INFORMATION_UNAVAILABLE",
                "SISTEMA",
                "Información del sistema no disponible",
                "No se obtuvo información suficiente del sistema operativo.",
                source="platform/psutil",
            )
        )
        return
    findings.append(
        _finding(
            "SYSTEM_INFORMATION",
            "SISTEMA",
            "Información del sistema recopilada",
            Severity.INFORMATION,
            "Se recopilaron versión de Windows, arquitectura y tiempo de actividad cuando estuvieron disponibles.",
            {
                "os": system.get("os"),
                "architecture": system.get("architecture"),
                "uptime_seconds": system.get("uptime_seconds"),
                "pending_updates": system.get("pending_updates"),
            },
            confidence="ALTA",
            source="platform/psutil",
        )
    )
