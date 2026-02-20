#IMPORTAMOS LIBRERIAS
import os
import platform
import psutil
import wmi
import subprocess
import shutil
from datetime import datetime

def mostrar_titulo():
    os.system("cls" if os.name == "nt" else "clear")

    titulo = r"""
    ██████╗ ██╗ █████╗  ██████╗ ███╗   ██╗ ██████╗ ███████╗████████╗██╗ ██████╗ ██████╗ 
    ██╔══██╗██║██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗██╔════╝╚══██╔══╝██║██╔════╝██╔═══██╗
    ██║  ██║██║███████║██║  ███╗██╔██╗ ██║██║   ██║███████╗   ██║   ██║██║     ██║   ██║
    ██║  ██║██║██╔══██║██║   ██║██║╚██╗██║██║   ██║╚════██║   ██║   ██║██║     ██║   ██║
    ██████╔╝██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝███████║   ██║   ██║╚██████╗╚██████╔╝
    ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═════╝
    
                HERRAMIENTA DE DIAGNÓSTICO DE HARDWARE
    """

    print(titulo)

# INFORMACION GENERAL
def info_sistema():
    print("\n===== SISTEMA OPERATIVO =====")
    print("Sistema:", platform.system())
    print("Versión:", platform.version())
    print("Release:", platform.release())
    print("Arquitectura:", platform.machine())


# INFO HARDWARE WINDOWS
def info_hardware():
    c = wmi.WMI()

    print("\n===== EQUIPO =====")
    for system in c.Win32_ComputerSystem():
        print("Fabricante:", system.Manufacturer)
        print("Modelo:", system.Model)
        print("RAM Total (GB):", round(int(system.TotalPhysicalMemory) / (1024**3), 2))

    print("\n===== PROCESADOR =====")
    for cpu in c.Win32_Processor():
        print("Nombre:", cpu.Name)
        print("Núcleos:", cpu.NumberOfCores)
        print("Hilos:", cpu.NumberOfLogicalProcessors)
        print("Frecuencia (MHz):", cpu.MaxClockSpeed)

    print("\n===== BIOS =====")
    for bios in c.Win32_BIOS():
        print("Versión BIOS:", bios.SMBIOSBIOSVersion)
        print("Fabricante:", bios.Manufacturer)
        print("Fecha:", bios.ReleaseDate)

# RAM DETALLE
def info_ram_detalle():
    c = wmi.WMI()

    print("\n===== RAM DETALLE =====")

    for ram in c.Win32_PhysicalMemory():
        capacidad = int(ram.Capacity) / (1024**3)
        print(f"Capacidad: {capacidad:.2f} GB")
        print("Tipo:", ram.MemoryType)
        print("Velocidad:", ram.Speed, "MHz")
        print("Fabricante:", ram.Manufacturer)
        print("----------------------")


# DISCO DURO
def info_discos():
    c = wmi.WMI()

    print("\n===== DISCOS =====")

    for disk in c.Win32_DiskDrive():
        size_gb = int(disk.Size) / (1024**3)
        print("Modelo:", disk.Model)
        print(f"Tamaño: {size_gb:.2f} GB")
        print("Interfaz:", disk.InterfaceType)
        print("----------------------")

# BATERIA
def info_bateria():
    battery = psutil.sensors_battery()

    print("\n===== BATERÍA =====")

    if battery:
        print("Porcentaje:", battery.percent, "%")
        print("Conectada:", battery.power_plugged)
    else:
        print("No se detectó batería (posible PC de escritorio)")

# TEMPERATURA
def info_temperatura():
    print("\n===== TEMPERATURA =====")

    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                for entry in entries:
                    print(name, entry.current, "°C")
        else:
            print("No disponible")
    except:
        print("No disponible")

# USO DISCO
def uso_disco():
    print("\n===== USO DE DISCO =====")

    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            print(f"Unidad: {part.device}")
            print(f"Total: {usage.total / (1024**3):.2f} GB")
            print(f"Usado: {usage.percent}%")
            print("----------------------")
        except:
            pass

# RECOMENDACIONES
def recomendaciones():
    print("\n===== RECOMENDACIONES =====")
    print("✔ Compatible con upgrade a SSD en la mayoría de casos.")
    print("✔ Revisar manual del fabricante para RAM máxima soportada.")
    print("✔ Si tiene HDD mecánico → upgrade a SSD mejora rendimiento.")
    print("✔ Si RAM < 8GB → recomendado ampliar a 16GB si es posible.")


# DIAGNOSTICO COMPLETO
def diagnostico():
    mostrar_titulo()
    info_sistema()
    info_hardware()
    info_ram_detalle()
    info_discos()
    info_bateria()
    info_temperatura()
    uso_disco()
    recomendaciones()

    input("\nPresiona ENTER para volver al menú...")

# MENU
def menu():
    while True:
        mostrar_titulo()

        print("\n1️⃣  Ejecutar Diagnóstico")
        print("2️⃣  Salir")

        opcion = input("\nSelecciona una opción: ")

        if opcion == "1":
            diagnostico()

        elif opcion == "2":
            break

        else:
            print("Opción inválida")

# MAIN
if __name__ == "__main__":
    menu()
