def mostrar_menu(secciones, opciones_finales=()):
    for titulo, opciones in secciones:
        if titulo:
            print(f"\n{titulo.upper()}")
        for tecla, descripcion in opciones:
            print(f"[{tecla}] {descripcion}")
    if opciones_finales:
        print()
        for tecla, descripcion in opciones_finales:
            print(f"[{tecla}] {descripcion}")


def pausar(mensaje="Presiona ENTER para volver al menú..."):
    input(f"\n{mensaje}")
