"""
utils/recomendaciones.py - Recomendaciones inteligentes basadas en los datos recopilados
"""


class Recomendaciones:

    @staticmethod
    def mostrar(resultados: dict):
        print("\n" + "=" * 50)
        print("   RECOMENDACIONES")
        print("=" * 50)

        tips = []

        # Analizar RAM
        ram = resultados.get("RAM", {})
        uso_ram_str = ram.get("Porcentaje de uso", "0 %")
        uso_ram = float(uso_ram_str.replace(" %", ""))
        if uso_ram > 85:
            tips.append("🔴 RAM al límite. Cierra aplicaciones o considera ampliar la RAM.")
        elif uso_ram > 65:
            tips.append("🟡 Uso de RAM elevado. Considera ampliar si ocurre frecuentemente.")

        slots = ram.get("slots", [])
        for slot in slots:
            tipo = slot.get("Tipo", "")
            if "DDR3" in tipo or "DDR2" in tipo:
                tips.append(f"⚠️  RAM tipo {tipo} detectada. DDR4/DDR5 ofrecería mejor rendimiento.")
                break

        # Analizar Discos
        discos = resultados.get("Discos", {})
        for part in discos.get("particiones", []):
            uso = float(part.get("Uso", "0 %").replace(" %", ""))
            unidad = part.get("Unidad", "?")
            if uso > 90:
                tips.append(f"🔴 Disco {unidad} casi lleno ({uso:.0f}%). Libera espacio urgente.")
            elif uso > 75:
                tips.append(f"🟡 Disco {unidad} con uso elevado ({uso:.0f}%). Considera limpiar archivos.")

        for disco in discos.get("discos_fisicos", []):
            if "HDD" in disco.get("Interfaz", "") or "IDE" in disco.get("Interfaz", ""):
                tips.append("💾 Se detectó disco HDD. Migrar a SSD puede mejorar el rendimiento x3-x5.")
            smart = disco.get("Estado SMART", "")
            if smart and smart.lower() not in ("ok", "pred fail", "no disponible"):
                tips.append(f"⚠️  Estado del disco: '{smart}'. Considera hacer un respaldo.")

        # Analizar Batería
        bateria = resultados.get("Batería", {})
        pct_bat_str = bateria.get("Porcentaje", "100 %")
        pct_bat = float(pct_bat_str.replace(" %", ""))
        if pct_bat < 15 and bateria.get("Conectada a corriente") == "No":
            tips.append("🔴 Batería crítica. Conecta el cargador pronto.")

        # Analizar Temperatura
        temps = resultados.get("Temperatura", {})
        for sensor, vals in temps.items():
            if isinstance(vals, dict):
                actual = vals.get("actual", 0)
                alta = vals.get("alta") or 85
                if actual >= alta:
                    tips.append(f"🔴 Temperatura crítica en {sensor}: {actual}°C. Limpia los ventiladores.")
                elif actual >= alta * 0.85:
                    tips.append(f"🟡 Temperatura elevada en {sensor}: {actual}°C. Revisa la refrigeración.")

        # Tips generales
        tips.append("✅ Mantén los drivers actualizados para mejor rendimiento y seguridad.")
        tips.append("✅ Revisa el manual del fabricante para conocer la RAM máxima soportada.")

        for tip in tips:
            print(f"\n  {tip}")
        print()
