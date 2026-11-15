# archivos.py
# En este archivo están las funciones para exportar e importar facturas (JSON y XML)
# y las funciones de la bitácora (archivo de texto).

import json
import xml.etree.ElementTree as ET
from datetime import datetime

ARCHIVO_BITACORA = "bitacora.txt"


# ---------------- JSON ----------------

def exportar_json(factura, ruta):
    # Armamos la lista de productos solo con los datos que pide el formato
    detalle = []
    for p in factura["detalle"]:
        producto = {
            "producto": p["producto"],
            "cantidad": p["cantidad"],
            "precio_unitario": p["precio_unitario"]
        }
        detalle.append(producto)

    datos = {
        "folio": factura["folio"],
        "cliente": factura["cliente"],
        "fecha": factura["fecha"],
        "detalle": detalle
    }

    with open(ruta, "w", encoding="utf-8") as archivo:
        # indent=2 acomoda el texto con sangría; ensure_ascii=False respeta los acentos
        json.dump(datos, archivo, indent=2, ensure_ascii=False)


def importar_json(ruta):
    with open(ruta, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    detalle = []
    for p in datos["detalle"]:
        producto = {
            "producto": p["producto"],
            "cantidad": int(p["cantidad"]),
            "precio_unitario": float(p["precio_unitario"])
        }
        detalle.append(producto)

    factura = {
        "folio": datos["folio"],
        "cliente": datos["cliente"],
        "fecha": datos["fecha"],
        "detalle": detalle
    }
    return factura


# ---------------- XML ----------------

def exportar_xml(factura, ruta):
    # Etiqueta principal <factura folio="...">
    raiz = ET.Element("factura")
    raiz.set("folio", factura["folio"])

    cliente = ET.SubElement(raiz, "cliente")
    cliente.text = factura["cliente"]

    fecha = ET.SubElement(raiz, "fecha")
    fecha.text = factura["fecha"]

    detalle = ET.SubElement(raiz, "detalle")

    # Un <item> por cada producto
    for p in factura["detalle"]:
        item = ET.SubElement(detalle, "item")

        producto = ET.SubElement(item, "producto")
        producto.text = p["producto"]

        cantidad = ET.SubElement(item, "cantidad")
        cantidad.text = str(p["cantidad"])

        precio = ET.SubElement(item, "precio_unitario")
        precio.text = str(p["precio_unitario"])

    arbol = ET.ElementTree(raiz)
    ET.indent(arbol)  # Acomoda las etiquetas con sangría para que se lea mejor
    arbol.write(ruta, encoding="utf-8", xml_declaration=True)


def importar_xml(ruta):
    arbol = ET.parse(ruta)
    raiz = arbol.getroot()

    folio = raiz.get("folio")
    cliente = raiz.find("cliente").text
    fecha = raiz.find("fecha").text

    detalle = []
    for item in raiz.find("detalle").findall("item"):
        producto = {
            "producto": item.find("producto").text,
            "cantidad": int(item.find("cantidad").text),
            "precio_unitario": float(item.find("precio_unitario").text)
        }
        detalle.append(producto)

    factura = {
        "folio": folio,
        "cliente": cliente,
        "fecha": fecha,
        "detalle": detalle
    }
    return factura


# ---------------- BITÁCORA ----------------

def escribir_bitacora(usuario, accion):
    # Agrega una línea al final del archivo con la fecha, el usuario y lo que hizo
    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ARCHIVO_BITACORA, "a", encoding="utf-8") as archivo:
        archivo.write(fecha_hora + " | " + usuario + " | " + accion + "\n")


def leer_bitacora():
    try:
        with open(ARCHIVO_BITACORA, "r", encoding="utf-8") as archivo:
            return archivo.read()
    except FileNotFoundError:
        return "Todavía no hay registros en la bitácora."
