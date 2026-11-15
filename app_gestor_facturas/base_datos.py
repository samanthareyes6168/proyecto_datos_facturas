# base_datos.py
# En este archivo están todas las funciones que trabajan con la base de datos SQLite.

import sqlite3

# Nombre del archivo donde se guarda la base de datos
NOMBRE_BD = "facturas.db"


def conectar():
    # Abre la base de datos (si el archivo no existe, SQLite lo crea)
    conexion = sqlite3.connect(NOMBRE_BD)
    return conexion


def crear_tablas():
    conexion = conectar()
    cursor = conexion.cursor()

    # Tabla de usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    # Tabla de facturas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT NOT NULL UNIQUE,
            cliente TEXT NOT NULL,
            fecha TEXT NOT NULL,
            total REAL NOT NULL,
            id_usuario INTEGER,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id)
        )
    """)

    # Tabla de detalle (los productos de cada factura)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detalle_factura (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_factura INTEGER NOT NULL,
            producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (id_factura) REFERENCES facturas(id)
        )
    """)

    # Si todavía no hay usuarios, creamos uno para poder entrar
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    cantidad_usuarios = cursor.fetchone()[0]
    if cantidad_usuarios == 0:
        cursor.execute("INSERT INTO usuarios (usuario, password) VALUES (?, ?)", ("admin", "1234"))

    conexion.commit()
    conexion.close()


def validar_usuario(usuario, password):
    # Regresa el id del usuario si los datos son correctos, o None si no lo son
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("SELECT id FROM usuarios WHERE usuario = ? AND password = ?", (usuario, password))
    resultado = cursor.fetchone()
    conexion.close()

    if resultado is None:
        return None
    return resultado[0]


def existe_folio(folio):
    # Regresa True si ya hay una factura con ese folio
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("SELECT id FROM facturas WHERE folio = ?", (folio,))
    resultado = cursor.fetchone()
    conexion.close()

    if resultado is None:
        return False
    return True


def guardar_factura(folio, cliente, fecha, productos, id_usuario):
    # productos es una lista de diccionarios con: producto, cantidad y precio_unitario

    # Primero calculamos el total de la factura
    total = 0
    for p in productos:
        total = total + p["cantidad"] * p["precio_unitario"]

    conexion = conectar()
    cursor = conexion.cursor()

    # Guardamos los datos generales de la factura
    cursor.execute(
        "INSERT INTO facturas (folio, cliente, fecha, total, id_usuario) VALUES (?, ?, ?, ?, ?)",
        (folio, cliente, fecha, total, id_usuario)
    )

    # lastrowid nos da el id que se le asignó a la factura que acabamos de insertar
    id_factura = cursor.lastrowid

    # Guardamos cada producto en la tabla de detalle
    for p in productos:
        subtotal = p["cantidad"] * p["precio_unitario"]
        cursor.execute(
            "INSERT INTO detalle_factura (id_factura, producto, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)",
            (id_factura, p["producto"], p["cantidad"], p["precio_unitario"], subtotal)
        )

    conexion.commit()
    conexion.close()


def obtener_facturas():
    # Regresa todas las facturas (sin el detalle)
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("SELECT folio, cliente, fecha, total FROM facturas ORDER BY id")
    facturas = cursor.fetchall()
    conexion.close()
    return facturas


def buscar_facturas(texto):
    # Busca facturas cuyo folio, cliente o fecha contengan el texto escrito
    conexion = conectar()
    cursor = conexion.cursor()
    patron = "%" + texto + "%"
    cursor.execute(
        "SELECT folio, cliente, fecha, total FROM facturas WHERE folio LIKE ? OR cliente LIKE ? OR fecha LIKE ? ORDER BY id",
        (patron, patron, patron)
    )
    facturas = cursor.fetchall()
    conexion.close()
    return facturas


def obtener_factura(folio):
    # Regresa un diccionario con toda la información de una factura, incluyendo sus productos
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("SELECT id, folio, cliente, fecha, total FROM facturas WHERE folio = ?", (folio,))
    datos = cursor.fetchone()

    if datos is None:
        conexion.close()
        return None

    factura = {
        "folio": datos[1],
        "cliente": datos[2],
        "fecha": datos[3],
        "total": datos[4],
        "detalle": []
    }

    # Buscamos los productos de esa factura usando su id
    cursor.execute(
        "SELECT producto, cantidad, precio_unitario, subtotal FROM detalle_factura WHERE id_factura = ?",
        (datos[0],)
    )
    filas = cursor.fetchall()
    conexion.close()

    for fila in filas:
        producto = {
            "producto": fila[0],
            "cantidad": fila[1],
            "precio_unitario": fila[2],
            "subtotal": fila[3]
        }
        factura["detalle"].append(producto)

    return factura
