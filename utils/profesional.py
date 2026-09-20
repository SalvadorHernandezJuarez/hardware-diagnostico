"""
utils/profesional.py - Análisis técnico del equipo en modo profesional
"""


class AnalisisProfesional:
    """Evalúa la salud del sistema y prioriza problemas técnicos."""

    @staticmethod
    def mostrar(resultados: dict):
        resumen = AnalisisProfesional.resumen(resultados)
        print("\n" + "=" * 60)
        print("   ANÁLISIS PROFESIONAL")
        print("=" * 60)
        print(f"  Estado general: {resumen['estado']}  |  Puntuación: {resumen['score']}/100")

        if not resumen["hallazgos"]:
            print("\n  ✅ No se detectaron problemas críticos en los indicadores analizados.")
            print("  ℹ️  El equipo se encuentra dentro de parámetros normales.")
            print("=" * 60)
            return

        print("\n  Hallazgos detectados:")
        for i, hallazgo in enumerate(resumen["hallazgos"], 1):
            print(f"  {i}. {hallazgo}")

        print("\n  Recomendación prioritaria:")
        print(f"  • {resumen['recomendacion']}")
        print("=" * 60)

    @staticmethod
    def resumen(resultados: dict) -> dict:
        score = 100
        hallazgos = []
        recomendaciones = []

        cpu = resultados.get("CPU", {})
        cpu_uso = AnalisisProfesional._extraer_porcentaje(cpu.get("Uso actual", "0 %"))
        if cpu_uso > 90:
            score -= 25
            hallazgos.append("CPU con uso muy alto (>90%). Revisar procesos, malware o carga excesiva.")
            recomendaciones.append("Optimiza la carga del sistema y revisa tareas de fondo o programas pesados.")
        elif cpu_uso > 75:
            score -= 12
            hallazgos.append("CPU con uso elevado (>75%). Posible presión sostenida del sistema.")
            recomendaciones.append("Controla procesos activos y revisa si hay aplicaciones con consumo anómalo.")

        ram = resultados.get("RAM", {})
        ram_uso = AnalisisProfesional._extraer_porcentaje(ram.get("Porcentaje de uso", "0 %"))
        if ram_uso > 90:
            score -= 25
            hallazgos.append("RAM casi saturada (>90%). Riesgo de rendimiento y bloqueo de programas.")
            recomendaciones.append("Cierra aplicaciones pesadas o considera ampliar memoria RAM.")
        elif ram_uso > 75:
            score -= 12
            hallazgos.append("RAM con uso elevado (>75%). El sistema puede mostrar lentitud bajo carga.")
            recomendaciones.append("Revisa procesos con alto consumo y evita multitarea intensiva.")

        discos = resultados.get("Discos", {})
        for part in discos.get("particiones", []):
            uso = AnalisisProfesional._extraer_porcentaje(part.get("Uso", "0 %"))
            unidad = part.get("Unidad", "Disco")
            if uso > 95:
                score -= 20
                hallazgos.append(f"Disco {unidad} casi lleno ({uso:.0f}%). Riesgo de fallo por espacio insuficiente.")
                recomendaciones.append(f"Libera espacio en {unidad} y revisa archivos temporales o programas pesados.")
            elif uso > 80:
                score -= 10
                hallazgos.append(f"Disco {unidad} con uso alto ({uso:.0f}%). Puede degradar el rendimiento.")
                recomendaciones.append(f"Limpia y optimiza el almacenamiento de {unidad}.")

        bateria = resultados.get("Batería", {})
        if "estado" not in bateria:
            pct = AnalisisProfesional._extraer_porcentaje(bateria.get("Porcentaje", "100 %"))
            conectada = bateria.get("Conectada a corriente", "Sí")
            if pct < 15 and conectada == "No":
                score -= 25
                hallazgos.append("Batería crítica (<15%) y sin alimentación externa.")
                recomendaciones.append("Conecta el cargador y revisa el estado de la batería del equipo.")
            elif pct < 30:
                score -= 10
                hallazgos.append("Batería baja, posible problema de autonomía del equipo.")
                recomendaciones.append("Revisa el sistema de carga o considera reemplazo si se agota rápido.")

        temperatura = resultados.get("Temperatura", {})
        if isinstance(temperatura, dict) and "estado" not in temperatura:
            for sensor, valores in temperatura.items():
                if not isinstance(valores, dict):
                    continue
                actual = valores.get("actual", 0)
                alta = valores.get("alta") or 85
                critica = valores.get("critica") or 100
                if actual >= critica:
                    score -= 30
                    hallazgos.append(f"Temperatura crítica en {sensor}: {actual}°C. Riesgo de sobrecalentamiento.")
                    recomendaciones.append(f"Revisa ventiladores y limpieza térmica en {sensor}.")
                elif actual >= alta:
                    score -= 15
                    hallazgos.append(f"Temperatura elevada en {sensor}: {actual}°C. Puede afectar rendimiento y estabilidad.")
                    recomendaciones.append(f"Verifica flujo de aire y limpieza del sistema en {sensor}.")

        gpu = resultados.get("GPU", {})
        if isinstance(gpu, dict) and "gpus" in gpu:
            for g in gpu.get("gpus", []):
                temp = AnalisisProfesional._extraer_temp(g.get("Temperatura", "0 °C"))
                if temp >= 90:
                    score -= 20
                    hallazgos.append(f"GPU en temperatura crítica ({temp}°C). Riesgo de throttling o daños.")
                    recomendaciones.append("Revisa ventilación de la tarjeta gráfica y limpieza del gabinete.")
                elif temp >= 80:
                    score -= 10
                    hallazgos.append(f"GPU con temperatura alta ({temp}°C). El rendimiento puede verse afectado.")
                    recomendaciones.append("Verifica la refrigeración de la GPU y el flujo de aire del equipo.")

        if score >= 85:
            estado = "OK"
        elif score >= 60:
            estado = "ALERTA"
        else:
            estado = "CRÍTICO"

        recomendacion = recomendaciones[0] if recomendaciones else "Mantén el equipo actualizado y revisa diagnósticos periódicos."
        score = max(0, min(100, score))

        return {
            "score": int(score),
            "estado": estado,
            "hallazgos": hallazgos,
            "recomendacion": recomendacion,
        }

    @staticmethod
    def _extraer_porcentaje(valor) -> float:
        if isinstance(valor, (int, float)):
            return float(valor)
        if not isinstance(valor, str):
            return 0.0
        texto = valor.replace("%", "").replace(",", ".").strip()
        try:
            return float(texto)
        except ValueError:
            return 0.0

    @staticmethod
    def _extraer_temp(valor) -> float:
        if isinstance(valor, (int, float)):
            return float(valor)
        if not isinstance(valor, str):
            return 0.0
        texto = valor.replace("°C", "").replace("C", "").replace(",", ".").strip()
        try:
            return float(texto)
        except ValueError:
            return 0.0
