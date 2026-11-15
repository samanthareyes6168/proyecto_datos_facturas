# main.py
# Archivo principal: aquí están las ventanas (login y ventana principal).
# Para ejecutar el programa se corre este archivo.

import sys
from datetime import date

from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem, QFileDialog
from PySide6.QtUiTools import QUiLoader

import base_datos
import archivos


# ==================== VENTANA DE LOGIN ====================

class VentanaLogin:
    def __init__(self):
        cargador = QUiLoader()
        self.ventana = cargador.load("login.ui")

        # Conectamos el botón con su función
        self.ventana.btnEntrar.clicked.connect(self.entrar)

        self.ventana.show()

    def entrar(self):
        usuario = self.ventana.txtUsuario.text()
        password = self.ventana.txtPassword.text()

        if usuario == "" or password == "":
            QMessageBox.warning(self.ventana, "Aviso", "Escribe tu usuario y contraseña.")
            return

        id_usuario = base_datos.validar_usuario(usuario, password)

        if id_usuario is None:
            QMessageBox.warning(self.ventana, "Error", "Usuario o contraseña incorrectos.")
            archivos.escribir_bitacora(usuario, "Intento fallido de inicio de sesión")
        else:
            archivos.escribir_bitacora(usuario, "Inició sesión")
            # Abrimos la ventana principal y cerramos el login
            self.principal = VentanaPrincipal(id_usuario, usuario)
            self.ventana.close()


# ==================== VENTANA PRINCIPAL ====================

class VentanaPrincipal:
    def __init__(self, id_usuario, usuario):
        cargador = QUiLoader()
        self.ventana = cargador.load("principal.ui")

        # Datos del usuario que inició sesión
        self.id_usuario = id_usuario
        self.usuario = usuario

        # Lista donde se guardan los productos de la factura que se está creando
        self.productos = []

        self.ventana.lblBienvenida.setText("Bienvenido(a), " + usuario)
        self.ventana.txtFecha.setText(str(date.today()))

        # Botones de la pestaña "Nueva factura"
        self.ventana.btnAgregar.clicked.connect(self.agregar_producto)
        self.ventana.btnQuitar.clicked.connect(self.quitar_producto)
        self.ventana.btnLimpiar.clicked.connect(self.limpiar)
        self.ventana.btnGuardar.clicked.connect(self.guardar_factura)

        # Botones de la pestaña "Consultar facturas"
        self.ventana.btnBuscar.clicked.connect(self.buscar)
        self.ventana.btnMostrarTodas.clicked.connect(self.mostrar_todas)
        self.ventana.btnVerDetalle.clicked.connect(self.ver_detalle)
        self.ventana.btnExportarJSON.clicked.connect(self.exportar_json)
        self.ventana.btnExportarXML.clicked.connect(self.exportar_xml)
        self.ventana.btnImportar.clicked.connect(self.importar)

        # Botón de la pestaña "Bitácora"
        self.ventana.btnActualizarBitacora.clicked.connect(self.mostrar_bitacora)

        # Cargamos los datos al abrir la ventana
        self.mostrar_todas()
        self.mostrar_bitacora()

        self.ventana.show()

    # ---------- Función de apoyo para llenar cualquier tabla ----------

    def llenar_tabla(self, tabla, filas):
        # filas es una lista de listas; cada lista interna es un renglón de la tabla
        tabla.setRowCount(len(filas))
        for i in range(len(filas)):
            for j in range(len(filas[i])):
                tabla.setItem(i, j, QTableWidgetItem(str(filas[i][j])))

    # ==================== PESTAÑA: NUEVA FACTURA ====================

    def agregar_producto(self):
        producto = self.ventana.txtProducto.text()
        cantidad = self.ventana.spinCantidad.value()
        texto_precio = self.ventana.txtPrecio.text()

        if producto == "":
            QMessageBox.warning(self.ventana, "Aviso", "Escribe el nombre del producto.")
            return

        # Intentamos convertir el precio a número decimal
        try:
            precio = float(texto_precio)
        except ValueError:
            QMessageBox.warning(self.ventana, "Aviso", "El precio debe ser un número.")
            return

        if precio <= 0:
            QMessageBox.warning(self.ventana, "Aviso", "El precio debe ser mayor a 0.")
            return

        nuevo = {
            "producto": producto,
            "cantidad": cantidad,
            "precio_unitario": precio
        }
        self.productos.append(nuevo)

        # Limpiamos los campos del producto para escribir el siguiente
        self.ventana.txtProducto.setText("")
        self.ventana.spinCantidad.setValue(1)
        self.ventana.txtPrecio.setText("")

        self.mostrar_productos()

    def mostrar_productos(self):
        # Muestra la lista de productos en la tabla y calcula el total
        filas = []
        total = 0
        for p in self.productos:
            precio = p["precio_unitario"]
            subtotal = p["cantidad"] * precio
            total = total + subtotal
            filas.append([p["producto"], p["cantidad"], f"${precio:.2f}", f"${subtotal:.2f}"])

        self.llenar_tabla(self.ventana.tablaDetalle, filas)
        self.ventana.lblTotal.setText(f"Total: ${total:.2f}")

    def quitar_producto(self):
        fila = self.ventana.tablaDetalle.currentRow()
        if fila == -1:
            QMessageBox.warning(self.ventana, "Aviso", "Selecciona el producto que quieres quitar.")
            return

        self.productos.pop(fila)
        self.mostrar_productos()

    def limpiar(self):
        self.ventana.txtFolio.setText("")
        self.ventana.txtCliente.setText("")
        self.ventana.txtFecha.setText(str(date.today()))
        self.ventana.txtProducto.setText("")
        self.ventana.spinCantidad.setValue(1)
        self.ventana.txtPrecio.setText("")
        self.productos = []
        self.mostrar_productos()

    def guardar_factura(self):
        folio = self.ventana.txtFolio.text()
        cliente = self.ventana.txtCliente.text()
        fecha = self.ventana.txtFecha.text()

        # Validaciones
        if folio == "" or cliente == "" or fecha == "":
            QMessageBox.warning(self.ventana, "Aviso", "Llena el folio, el cliente y la fecha.")
            return

        if len(self.productos) == 0:
            QMessageBox.warning(self.ventana, "Aviso", "Agrega al menos un producto.")
            return

        if base_datos.existe_folio(folio):
            QMessageBox.warning(self.ventana, "Aviso", "Ya existe una factura con el folio " + folio + ".")
            return

        base_datos.guardar_factura(folio, cliente, fecha, self.productos, self.id_usuario)
        archivos.escribir_bitacora(self.usuario, "Creó la factura " + folio)

        QMessageBox.information(self.ventana, "Listo", "La factura se guardó correctamente.")
        self.limpiar()
        self.mostrar_todas()

    # ==================== PESTAÑA: CONSULTAR FACTURAS ====================

    def mostrar_facturas(self, facturas):
        # facturas es la lista que regresa la base de datos: (folio, cliente, fecha, total)
        filas = []
        for f in facturas:
            filas.append([f[0], f[1], f[2], f"${f[3]:.2f}"])
        self.llenar_tabla(self.ventana.tablaFacturas, filas)

        # Limpiamos el detalle porque cambió la lista
        self.ventana.tablaConsulta.setRowCount(0)
        self.ventana.lblTotalConsulta.setText("Total: $0.00")

    def mostrar_todas(self):
        self.ventana.txtBuscar.setText("")
        facturas = base_datos.obtener_facturas()
        self.mostrar_facturas(facturas)

    def buscar(self):
        texto = self.ventana.txtBuscar.text()
        facturas = base_datos.buscar_facturas(texto)
        self.mostrar_facturas(facturas)

        if len(facturas) == 0:
            QMessageBox.information(self.ventana, "Búsqueda", "No se encontraron facturas.")

    def folio_seleccionado(self):
        # Regresa el folio de la factura seleccionada en la tabla, o "" si no hay ninguna
        fila = self.ventana.tablaFacturas.currentRow()
        if fila == -1:
            QMessageBox.warning(self.ventana, "Aviso", "Primero selecciona una factura de la tabla.")
            return ""
        return self.ventana.tablaFacturas.item(fila, 0).text()

    def ver_detalle(self):
        folio = self.folio_seleccionado()
        if folio == "":
            return

        factura = base_datos.obtener_factura(folio)

        filas = []
        for p in factura["detalle"]:
            filas.append([p["producto"], p["cantidad"], f"${p['precio_unitario']:.2f}", f"${p['subtotal']:.2f}"])

        self.llenar_tabla(self.ventana.tablaConsulta, filas)
        self.ventana.lblTotalConsulta.setText(f"Total de {folio} ({factura['cliente']}): ${factura['total']:.2f}")

    def exportar_json(self):
        folio = self.folio_seleccionado()
        if folio == "":
            return

        # getSaveFileName regresa dos valores: la ruta elegida y el filtro
        ruta, filtro = QFileDialog.getSaveFileName(self.ventana, "Exportar a JSON", folio + ".json", "Archivos JSON (*.json)")
        if ruta == "":
            return  # El usuario canceló

        factura = base_datos.obtener_factura(folio)
        archivos.exportar_json(factura, ruta)
        archivos.escribir_bitacora(self.usuario, "Exportó la factura " + folio + " a JSON")
        QMessageBox.information(self.ventana, "Listo", "Factura exportada a JSON.")

    def exportar_xml(self):
        folio = self.folio_seleccionado()
        if folio == "":
            return

        ruta, filtro = QFileDialog.getSaveFileName(self.ventana, "Exportar a XML", folio + ".xml", "Archivos XML (*.xml)")
        if ruta == "":
            return

        factura = base_datos.obtener_factura(folio)
        archivos.exportar_xml(factura, ruta)
        archivos.escribir_bitacora(self.usuario, "Exportó la factura " + folio + " a XML")
        QMessageBox.information(self.ventana, "Listo", "Factura exportada a XML.")

    def importar(self):
        ruta, filtro = QFileDialog.getOpenFileName(self.ventana, "Importar factura", "", "Facturas (*.json *.xml)")
        if ruta == "":
            return

        # Leemos el archivo según su extensión
        try:
            if ruta.endswith(".json"):
                factura = archivos.importar_json(ruta)
            else:
                factura = archivos.importar_xml(ruta)
        except Exception:
            QMessageBox.warning(self.ventana, "Error", "El archivo no tiene el formato correcto.")
            return

        if base_datos.existe_folio(factura["folio"]):
            QMessageBox.warning(self.ventana, "Aviso", "Ya existe una factura con el folio " + factura["folio"] + ".")
            return

        base_datos.guardar_factura(factura["folio"], factura["cliente"], factura["fecha"], factura["detalle"], self.id_usuario)
        archivos.escribir_bitacora(self.usuario, "Importó la factura " + factura["folio"])
        QMessageBox.information(self.ventana, "Listo", "Factura " + factura["folio"] + " importada correctamente.")
        self.mostrar_todas()

    # ==================== PESTAÑA: BITÁCORA ====================

    def mostrar_bitacora(self):
        texto = archivos.leer_bitacora()
        self.ventana.txtBitacora.setPlainText(texto)


# ==================== INICIO DEL PROGRAMA ====================

app = QApplication(sys.argv)
base_datos.crear_tablas()
login = VentanaLogin()
sys.exit(app.exec())
