"""Terminal presentation for deterministic diagnostic runs."""

from core.diagnostic_engine import DiagnosticRun, run_hardware_diagnostics
from core.result import DiagnosticResult
from core.severity import Severity
from ui.components import pausar
from modules.hardware import HardwareInfo


SUPPORTED_GUIDED_OPTIONS = {
    "1": ("Equipo lento", {"CPU", "RAM", "DISCO", "TEMPERATURAS", "SISTEMA"}),
    "2": ("Se calienta", {"TEMPERATURAS", "CPU", "GPU", "DISCO"}),
    "3": ("Se apaga", {"BATERÍA", "TEMPERATURAS", "CPU", "SISTEMA"}),
    "4": ("Se reinicia", {"CPU", "RAM", "DISCO", "TEMPERATURAS", "SISTEMA"}),
    "5": ("No tiene Internet", set()),
    "6": ("Poco espacio", {"DISCO", "ALMACENAMIENTO"}),
    "7": ("Problemas de batería", {"BATERÍA"}),
    "8": ("Problemas de pantalla", {"GPU", "PANTALLA"}),
    "9": ("Problemas de audio", {"AUDIO"}),
    "10": (
        "Otro",
        {"CPU", "RAM", "DISCO", "GPU", "BATERÍA", "TEMPERATURAS", "SISTEMA"},
    ),
}

GUIDED_OPTIONS = (
    ("1", "Equipo lento"),
    ("2", "Se calienta"),
    ("3", "Se apaga"),
    ("4", "Se reinicia"),
    ("5", "No tiene Internet"),
    ("6", "Poco espacio"),
    ("7", "Problemas de batería"),
    ("8", "Problemas de pantalla"),
    ("9", "Problemas de audio"),
    ("10", "Otro"),
)

GUIDED_NEXT_STEPS = {
    "Equipo lento": (
        "Repite la medición cuando el equipo esté en reposo.",
        "Revisa si el uso de CPU o RAM permanece elevado y qué procesos lo generan.",
        "Comprueba el espacio libre y cuándo comenzó la lentitud.",
    ),
    "Se calienta": (
        "Coloca el equipo sobre una superficie dura y despeja las rejillas de ventilación.",
        "Cierra cargas intensivas y comprueba si baja la temperatura.",
        "Si se apaga por temperatura o está demasiado caliente al tacto, apágalo y deja que se enfríe.",
    ),
    "Se apaga": (
        "Comprueba el cargador, la toma de corriente y si ocurre también con la batería cargada.",
        "Anota la hora del apagado y si el equipo estaba caliente o bajo carga.",
        "Si se repite, revisa el Historial de confiabilidad de Windows o solicita una revisión técnica.",
    ),
    "Se reinicia": (
        "Anota la hora, el código de error o el pantallazo azul si aparece.",
        "Comprueba si el reinicio coincide con una actualización, controlador o aplicación reciente.",
        "Consulta el Historial de confiabilidad de Windows para ver errores registrados.",
    ),
    "Poco espacio": (
        "Identifica qué unidad está llena y revisa los archivos grandes antes de eliminarlos.",
        "Haz una copia de seguridad de los archivos importantes antes de liberar espacio.",
        "Usa Configuración de Windows o Sensor de almacenamiento para limpiar archivos temporales.",
    ),
    "Problemas de batería": (
        "Comprueba si el problema ocurre conectado a la corriente y prueba un cargador compatible.",
        "Compara la capacidad actual con la capacidad de diseño en el informe de batería de Windows.",
        "Si la batería está hinchada o dañada, deja de usar el equipo y busca servicio técnico.",
    ),
    "Problemas de pantalla": (
        "Comprueba el brillo, la conexión y, si es posible, prueba con un monitor externo.",
        "Anota si la imagen falla antes de iniciar Windows o solo dentro de una aplicación.",
        "El inventario detecta dispositivos, pero no prueba el panel ni el cable físicamente.",
    ),
    "Problemas de audio": (
        "Selecciona la salida correcta y revisa el volumen y el mezclador de Windows.",
        "Prueba otro dispositivo de salida y verifica por separado micrófono y altavoces.",
        "El inventario detecta dispositivos, pero no reproduce ni graba audio para probarlos.",
    ),
    "Otro": (
        "Anota el mensaje exacto, la hora y qué estabas haciendo cuando ocurrió.",
        "Indica si el problema empezó después de un cambio de hardware, actualización o aplicación.",
        "Repite la prueba si es intermitente y conserva cualquier código de error.",
    ),
}


def _component_group(component, code=""):
    if "TEMPERATURE" in code or "TEMPERATURA" in code:
        return "TEMPERATURAS"
    name = component.upper()
    if name.startswith("CPU"):
        return "CPU"
    if name.startswith("RAM"):
        return "RAM"
    if name.startswith("DISCO") or name.startswith("ALMACENAMIENTO"):
        return "DISCO"
    if name.startswith("GPU"):
        return "GPU"
    if name.startswith("BATERÍA"):
        return "BATERÍA"
    if name.startswith("PANTALLA"):
        return "PANTALLA"
    if name.startswith("AUDIO"):
        return "AUDIO"
    if name.startswith("TEMP"):
        return "TEMPERATURAS"
    if name.startswith("SISTEMA"):
        return "SISTEMA"
    return name


class DiagnosticsMenu:
    def __init__(self, screens, history_logger=None, network_diagnostic=None):
        self.screens = screens
        self.history_logger = history_logger
        self.network_diagnostic = network_diagnostic

    def mostrar(self, professional=False, guided=False):
        guided_result = self._guided_choice() if guided else None
        if guided and guided_result is None:
            return None
        if guided_result and guided_result[0] == "No tiene Internet":
            if self.network_diagnostic is None:
                print("\nEl diagnóstico automático de red no está disponible.")
                return None
            return self.network_diagnostic(professional)

        self.screens.mostrar_encabezado()
        print("╔════════════════════════════════════════════╗")
        title = "DIAGNÓSTICO GUIADO" if guided_result else "DIAGNÓSTICO GENERAL"
        print(f"║          {title:<32}║")
        print("╚════════════════════════════════════════════╝")
        if guided_result:
            print(f"Síntoma seleccionado: {guided_result[0]}")
        print("\nAnalizando equipo...")
        run = run_hardware_diagnostics(
            mode="profesional" if professional else "normal"
        )
        if guided_result:
            included = guided_result[1]
            run = DiagnosticRun(
                timestamp=run.timestamp,
                mode=run.mode,
                data=run.data,
                results=[
                    finding for finding in run.results
                    if _component_group(finding.component, finding.code) in included
                ],
            )
            if guided_result[0] == "Problemas de pantalla":
                self._add_device_inventory(run, "display", "PANTALLA")
            elif guided_result[0] == "Problemas de audio":
                self._add_device_inventory(run, "audio", "AUDIO")

        self._persist(
            run,
            (
                f"Diagnóstico guiado: {guided_result[0]}"
                if guided_result
                else "Diagnóstico determinístico"
            ),
        )
        self.screens.estado = run.severity
        self._show_summary(run)
        if guided_result:
            self._show_guided_next_steps(guided_result[0])
        if (
            any(
                finding.component == "RAM"
                and finding.severity in (Severity.ALERT, Severity.CRITICAL)
                for finding in run.results
            )
            and run.data.get("processes", {}).get("top_memory")
        ):
            self._show_top_processes(run.data["processes"]["top_memory"])
        return self._interaction(run, professional, guided=guided)

    def _guided_choice(self):
        self.screens.mostrar_encabezado()
        print("DIAGNÓSTICO GUIADO")
        print("¿Qué problema presenta el equipo?")
        for key, label in GUIDED_OPTIONS:
            print(f"[{key}] {label}")
        print("[0] Volver")
        option = input("\nSelecciona un síntoma: ").strip()
        if option == "0":
            return None
        if option in SUPPORTED_GUIDED_OPTIONS:
            return SUPPORTED_GUIDED_OPTIONS[option]
        print("\nOpción inválida.")
        pausar()
        return None

    @staticmethod
    def _add_device_inventory(run, category, component):
        collector = HardwareInfo()
        title = "display" if category == "display" else "audio"
        try:
            data = getattr(collector, title)()
            error = None
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exception:
            import logging

            logging.getLogger("hardware_diagnostico").exception(
                "No se pudo recopilar información de %s", category
            )
            data = {}
            error = str(exception)
        run.data[category] = data
        if error:
            run.results.append(
                DiagnosticResult(
                    code=f"GUIDED_{category.upper()}_DATA_UNAVAILABLE",
                    component=component,
                    title=f"Información de {category} no disponible",
                    description="No fue posible recopilar la información de los dispositivos.",
                    evidence={"error": error},
                    recommendation="Revisa el registro de diagnóstico para más detalles.",
                    source="WMI/CIM",
                )
            )
            return
        devices = data.get("monitors" if category == "display" else "devices") or []
        reported_errors = [
            device
            for device in devices
            if str(device.get("status") or "").strip().casefold()
            in {
                "error",
                "degraded",
                "pred fail",
                "lost comm",
                "no contact",
                "nonrecover",
                "service",
                "stressed",
            }
        ]
        run.results.append(
            DiagnosticResult(
                code=(
                    f"GUIDED_{category.upper()}_DEVICE_STATUS"
                    if reported_errors
                    else f"GUIDED_{category.upper()}_INVENTORY"
                ),
                component=component,
                title=(
                    f"Windows reporta estados anómalos en {category}"
                    if reported_errors
                    else f"Inventario de dispositivos de {category}"
                ),
                description=(
                    "Windows reporta un estado anómalo en uno o más dispositivos; "
                    "esto requiere comprobación y no confirma por sí solo una falla física."
                    if reported_errors
                    else "Se recopiló información del dispositivo; esto no prueba "
                    "su funcionamiento físico."
                ),
                evidence=data,
                severity=Severity.ALERT if reported_errors else Severity.INFORMATION,
                recommendation=(
                    "Comprueba conexiones, configuración y controladores; "
                    "confirma el problema con una prueba funcional."
                    if reported_errors
                    else "Comprueba conexiones y prueba el dispositivo en Windows; "
                    "el inventario por sí solo no confirma una falla."
                ),
                source="WMI/CIM",
            )
        )

    def _persist(self, run, title="Diagnóstico determinístico"):
        if not self.history_logger:
            return
        try:
            self.history_logger.iniciar_sesion()
            self.history_logger.registrar(
                title,
                run.to_dict(include_data=False),
            )
        except Exception:
            import logging

            logging.getLogger("hardware_diagnostico").exception(
                "No se pudo guardar el diagnóstico en el historial"
            )

    def _show_summary(self, run):
        labels = (
            ("CPU", "CPU"),
            ("RAM", "RAM"),
            ("DISCO", "Almacenamiento"),
            ("GPU", "GPU"),
            ("BATERÍA", "Batería"),
            ("TEMPERATURAS", "Temperaturas"),
            ("SISTEMA", "Sistema"),
            ("PANTALLA", "Pantalla"),
            ("AUDIO", "Audio"),
        )
        statuses = run.component_statuses
        for key, label in labels:
            status = statuses.get(key)
            icon = status.display if status is not None else "ℹ SIN DATOS"
            print(f"[{icon}] {label}")
        print("\n" + "─" * 44)
        print("RESULTADO")
        print(f"Estado: {run.severity.display}")
        summary = run.summary
        print(f"Problemas encontrados: {summary['problems']}")
        print(f"Alertas: {summary['alerts']}")
        print(f"Críticos: {summary['critical']}")
        if summary["information"]:
            print(f"Datos informativos / no disponibles: {summary['information']}")
        if not self._actionable(run):
            print(
                "\nNo se detectaron alertas automáticas en las métricas disponibles; "
                "esto no descarta fallas intermitentes o físicas."
            )
        print("─" * 44)

    @staticmethod
    def _show_guided_next_steps(symptom):
        steps = GUIDED_NEXT_STEPS.get(symptom)
        if not steps:
            return
        print(f"\nSIGUIENTES PASOS: {symptom.upper()}")
        for step in steps:
            print(f"  • {step}")

    @staticmethod
    def _actionable(run):
        return [
            finding for finding in run.results
            if finding.severity in (Severity.ALERT, Severity.CRITICAL)
        ]

    @staticmethod
    def _show_top_processes(processes):
        print("\nPROCESOS CON MAYOR CONSUMO DE RAM")
        print("─" * 44)
        print(f"{'Proceso':<28} {'RAM':>10}")
        for process in processes:
            name = process["name"][:27]
            memory_gb = process["rss_bytes"] / (1024 ** 3)
            print(f"{name:<28} {memory_gb:>8.2f} GB")

    def _interaction(self, run, professional, guided=False):
        while True:
            print("\n[1] Ver detalles")
            print("[2] Ver recomendaciones")
            print("[3] Generar reporte PDF")
            print("[0] Volver")
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return run
            if option == "1":
                self._show_findings(run, professional, guided=guided)
            elif option == "2":
                self._show_recommendations(run)
            elif option == "3":
                from reports.exportar import ExportarPDF

                ExportarPDF.generar_diagnostico(run)
            else:
                print("Opción inválida.")

    def _show_findings(self, run, professional, guided=False):
        visible = (
            run.results
            if professional or guided
            else [
                finding for finding in run.results
                if finding.severity != Severity.NORMAL
            ]
        )
        if not visible:
            print("\nNo hay hallazgos para mostrar.")
            return
        print("\nHALLAZGOS")
        for index, finding in enumerate(visible, 1):
            print(
                f"[{index}] {finding.severity.display} "
                f"{finding.component} — {finding.title}"
            )
        selection = input("\nSelecciona un hallazgo (0 para volver): ").strip()
        if not selection.isdigit() or selection == "0":
            return
        index = int(selection) - 1
        if index < 0 or index >= len(visible):
            print("Número de hallazgo inválido.")
            return
        self._show_finding(visible[index], professional)

    @staticmethod
    def _show_finding(finding, professional):
        print("\n╔════════════════════════════════════════════╗")
        print("║             DETALLE DEL PROBLEMA           ║")
        print("╚════════════════════════════════════════════╝")
        print(f"\nProblema: {finding.title}")
        print(f"Componente: {finding.component}")
        print(f"Severidad: {finding.severity.display}")
        print(f"Descripción: {finding.description}")
        if professional:
            print(f"Evidencia: {finding.evidence}")
            if finding.current_value is not None:
                print(f"Valor actual: {finding.current_value}")
            if finding.expected_value is not None:
                print(f"Valor esperado: {finding.expected_value}")
        else:
            evidence = _normal_evidence(finding.evidence)
            if evidence:
                print(f"Evidencia: {evidence}")
        if finding.possible_causes:
            print("Posibles causas a revisar (no confirmadas):")
            for cause in finding.possible_causes:
                print(f"  • {cause}")
        if finding.recommendation:
            print(f"Recomendación: {finding.recommendation}")
        if professional:
            print(f"\nCódigo: {finding.code}")
            print(f"Regla: {finding.rule_id}")
            print(f"Confianza: {finding.confidence}")
            print(f"Fuente: {finding.source}")
            print(f"Prioridad de regla: {finding.priority}")
            print(f"Timestamp: {finding.timestamp}")

    @staticmethod
    def _show_recommendations(run):
        findings = [
            finding for finding in run.results
            if finding.recommendation
            and finding.severity in (Severity.ALERT, Severity.CRITICAL)
        ]
        if not findings:
            print("\nNo hay recomendaciones correctivas basadas en los datos actuales.")
            return
        print("\nRECOMENDACIONES")
        for finding in findings:
            print(
                f"\n{finding.severity.display} {finding.component}: "
                f"{finding.recommendation}"
            )


def _normal_evidence(evidence):
    if not isinstance(evidence, dict):
        return ""
    fields = (
        ("volume", "Unidad"),
        ("usage_percent", "Uso de RAM"),
        ("mean_percent", "Uso medio de CPU"),
        ("available_gb", "Memoria disponible (GB)"),
        ("free_gb", "Espacio libre (GB)"),
        ("free_percent", "Espacio libre (%)"),
        ("temperature_c", "Temperatura (°C)"),
        ("health_percent", "Salud de batería (%)"),
        ("health", "Salud SMART"),
        ("status", "Estado Windows"),
        ("percentage", "Carga de batería (%)"),
    )
    values = [
        f"{label}: {evidence[key]}"
        for key, label in fields
        if evidence.get(key) is not None
    ]
    if "monitors" in evidence:
        monitors = evidence.get("monitors") or []
        names = [
            f"{monitor.get('name') or 'Monitor'} ({monitor.get('status') or 'estado desconocido'})"
            for monitor in monitors
        ]
        if names:
            values.append("Monitores: " + ", ".join(names))
        if evidence.get("resolution"):
            values.append(f"Resolución: {evidence['resolution']}")
    if "devices" in evidence:
        devices = evidence.get("devices") or []
        names = [
            f"{device.get('name') or 'Dispositivo'} ({device.get('status') or 'estado desconocido'})"
            for device in devices
        ]
        if names:
            values.append("Dispositivos: " + ", ".join(names))
    return "; ".join(values)
