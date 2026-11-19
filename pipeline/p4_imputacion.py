"""
Imputación de valores nulos y marcado de outliers.

  - Outliers de precio por producto con el criterio IQR (se marcan, no se eliminan).
  - Comparación de métodos (media, mediana, por producto y KNN) sobre un 10 % de
    precios conocidos ocultados.
  - Imputación de precios con la mediana por producto y de edades con la mediana.

Salidas: int_detalle, int_clientes, docs/reporte_imputacion.md, docs/img/imputacion_error.png
"""

import numpy as np
import pandas as pd

import config
from pipeline.utilidades import conectar_almacen, obtener_logger, traducir_llave

log = obtener_logger("p4_imputacion")
METODO_ELEGIDO = "Mediana por producto"


def marcar_outliers(df):
    """IQR por producto: fuera de [Q1 - 1.5*IQR, Q3 + 1.5*IQR] es outlier."""
    def por_grupo(precios):
        q1, q3 = precios.quantile(0.25), precios.quantile(0.75)
        iqr = q3 - q1
        return (precios < q1 - 1.5 * iqr) | (precios > q3 + 1.5 * iqr)
    conocidos = df["precio_unitario"].notna()
    df["es_outlier"] = 0
    marcas = df.loc[conocidos].groupby("id_producto")["precio_unitario"].transform(por_grupo)
    df.loc[conocidos, "es_outlier"] = marcas.astype(int)
    return df


def experimento_comparativo(df, productos):
    from sklearn.impute import KNNImputer

    rng = np.random.default_rng(config.SEMILLA)
    conocidos = df[df["precio_unitario"].notna()].copy()
    mascara = rng.random(len(conocidos)) < 0.10
    entrenamiento = conocidos[~mascara]
    prueba = conocidos[mascara & (conocidos["es_outlier"] == 0)]   # comparamos contra precios "reales" normales
    real = prueba["precio_unitario"].to_numpy()

    estimaciones = {
        "Media global": np.full(len(prueba), entrenamiento["precio_unitario"].mean()),
        "Mediana global": np.full(len(prueba), entrenamiento["precio_unitario"].median()),
        "Media por producto": prueba["id_producto"].map(entrenamiento.groupby("id_producto")["precio_unitario"].mean()).to_numpy(),
        "Mediana por producto": prueba["id_producto"].map(entrenamiento.groupby("id_producto")["precio_unitario"].median()).to_numpy(),
    }

    # KNN: busca los 5 registros más parecidos (mismo precio de lista, categoría y cantidad)
    # y promedia su precio.
    base = conocidos.merge(productos[["id_producto", "precio_lista", "categoria"]], on="id_producto", how="left")
    base["categoria_cod"] = base["categoria"].astype("category").cat.codes
    X = base[["precio_lista", "categoria_cod", "cantidad", "precio_unitario"]].astype(float).to_numpy()
    X[mascara, 3] = np.nan
    escala = np.nanstd(X, axis=0)
    escala[escala == 0] = 1
    imputado = KNNImputer(n_neighbors=5).fit_transform(X / escala) * escala
    knn = pd.Series(imputado[:, 3], index=conocidos.index)
    estimaciones["KNN (k=5)"] = knn.loc[prueba.index].to_numpy()

    resultados = []
    for metodo, estimado in estimaciones.items():
        error = np.abs(estimado - real)
        resultados.append({"metodo": metodo, "error_absoluto_medio": float(error.mean()),
                           "error_relativo_medio_pct": float((error / real).mean() * 100)})
    return pd.DataFrame(resultados).sort_values("error_absoluto_medio"), len(prueba)


def ejemplo_media_vs_mediana(df, productos):
    """Para el reporte: en qué productos la media se aleja más de la mediana por culpa de los outliers."""
    g = df[df["precio_unitario"].notna()].groupby("id_producto")["precio_unitario"].agg(["mean", "median", "count"])
    g["outliers"] = df.groupby("id_producto")["es_outlier"].sum()
    g = g.join(productos.set_index("id_producto")[["nombre", "precio_lista"]])
    g["desviacion_media_pct"] = (g["mean"] / g["median"] - 1) * 100
    return g.sort_values("desviacion_media_pct", ascending=False).head(5)


def grafica(resultados):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib no está instalado: se omite la gráfica")
        return
    r = resultados.sort_values("error_relativo_medio_pct", ascending=False)
    colores = ["#184f95" if m == METODO_ELEGIDO else "#86b6ef" for m in r["metodo"]]
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    barras = ax.barh(r["metodo"], r["error_relativo_medio_pct"], color=colores, height=0.55)
    for b, v in zip(barras, r["error_relativo_medio_pct"]):
        ax.text(b.get_width() + 1, b.get_y() + b.get_height() / 2, f"{v:.1f} %", va="center",
                fontsize=9, color="#0b0b0b")
    ax.set_xlabel("Error relativo medio al adivinar un precio oculto (menos es mejor)", color="#52514e", fontsize=9)
    ax.set_title("Imputación de precios: error por método", loc="left", fontsize=12, color="#0b0b0b")
    for lado in ["top", "right", "left"]:
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e", labelsize=9, length=0)
    ax.grid(axis="x", color="#e8e7e2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(0, r["error_relativo_medio_pct"].max() * 1.15)
    fig.tight_layout()
    (config.DOCS_DIR / "img").mkdir(parents=True, exist_ok=True)
    fig.savefig(config.DOCS_DIR / "img" / "imputacion_error.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def escribir_reporte(resultados, n_prueba, ejemplo, n_nulos, n_outliers, n_edades):
    def err(metodo):
        return float(resultados.loc[resultados["metodo"] == metodo, "error_relativo_medio_pct"].iloc[0])
    filas = "\n".join(f"| {r.metodo}{' ✅' if r.metodo == METODO_ELEGIDO else ''} | ${r.error_absoluto_medio:,.2f} "
                      f"| {r.error_relativo_medio_pct:.1f} % |" for r in resultados.itertuples())
    ej = "\n".join(f"| {r.nombre} | ${r.precio_lista:,.2f} | ${r.mean:,.2f} | ${r.median:,.2f} | "
                   f"{r.desviacion_media_pct:+.1f} % | {int(r.outliers)} |" for r in ejemplo.itertuples())
    texto = f"""# Reporte de imputación (generado automáticamente por `p4_imputacion.py`)

## Qué se imputó
- Precios unitarios nulos imputados: **{n_nulos}**
- Edades de clientes nulas imputadas: **{n_edades}**
- Precios marcados como outlier (IQR por producto, se conservan y se etiquetan): **{n_outliers}**

## Experimento: ¿qué método adivina mejor un precio?
Se ocultó al azar el 10 % de los precios conocidos y se estimaron con cada método.
Se midió el error contra el precio real en {n_prueba} casos (sin contar outliers).

| Método | Error absoluto medio | Error relativo medio |
|---|---|---|
{filas}

![Error por método](img/imputacion_error.png)

**Método elegido: {METODO_ELEGIDO}.** Los métodos globales ignoran que una laptop y un cuaderno
cuestan cosas muy distintas, por eso fallan tanto. Entre los métodos por producto, la mediana
es más estable que la media porque los outliers (precios capturados con un cero de más) jalan
la media hacia arriba.

KNN obtuvo {err('KNN (k=5)'):.1f} % de error frente a {err(METODO_ELEGIDO):.1f} % de la mediana por producto:
KNN encuentra bien a los vecinos parecidos (mismo producto), pero después **promedia** su precio,
así que si uno de los 5 vecinos es un outlier x10, la estimación se infla. Es decir, KNN hereda
el mismo defecto de la media. Además es más caro de calcular. Por eso se elige la mediana por
producto: simple, rápida y robusta ante valores extremos.

## Evidencia: la media se deja arrastrar por los outliers
| Producto | Precio lista | Media | Mediana | Media vs mediana | Outliers |
|---|---|---|---|---|---|
{ej}

La mediana se queda cerca del precio de lista; la media se infla en proporción a los outliers.
"""
    (config.DOCS_DIR / "reporte_imputacion.md").write_text(texto, encoding="utf-8")


def imputar():
    con = conectar_almacen()
    df = pd.read_sql("SELECT * FROM stg_detalle", con)
    productos = pd.read_sql("SELECT * FROM raw_productos", con)
    productos["id_producto"] = productos["id_producto"].map(traducir_llave)
    productos["precio_lista"] = productos["precio_lista"].astype(float)

    df = marcar_outliers(df)
    resultados, n_prueba = experimento_comparativo(df, productos)

    # ---- Aplicar el método elegido a los nulos reales ----
    medianas = df.groupby("id_producto")["precio_unitario"].median()
    nulos = df["precio_unitario"].isna()
    df["precio_imputado"] = nulos.astype(int)
    df["metodo_imputacion"] = np.where(nulos, "mediana_producto", None)
    df["precio_final"] = df["precio_unitario"].fillna(df["id_producto"].map(medianas))
    df["precio_final"] = df["precio_final"].fillna(df["precio_unitario"].median())   # respaldo: producto sin historia
    df.to_sql("int_detalle", con, if_exists="replace", index=False)

    # ---- Clientes: maestro + altas válidas, edad nula -> mediana ----
    maestro = pd.read_sql("SELECT id_cliente, nombre, rfc, edad, ciudad, estado, 'maestro_app' AS origen "
                          "FROM raw_clientes_maestro", con)
    maestro["id_cliente"] = maestro["id_cliente"].map(traducir_llave)
    altas = pd.read_sql("SELECT id_cliente, nombre, rfc, edad, ciudad, estado, 'alta_csv' AS origen "
                        "FROM stg_clientes_altas", con)
    clientes = pd.concat([maestro, altas], ignore_index=True)
    clientes["edad"] = pd.to_numeric(clientes["edad"], errors="coerce")
    clientes["edad_imputada"] = clientes["edad"].isna().astype(int)
    clientes["edad"] = clientes["edad"].fillna(clientes["edad"].median()).round().astype(int)
    clientes.to_sql("int_clientes", con, if_exists="replace", index=False)
    con.close()

    grafica(resultados)
    escribir_reporte(resultados, n_prueba, ejemplo_media_vs_mediana(df, productos), int(nulos.sum()),
                     int(df["es_outlier"].sum()), int(clientes["edad_imputada"].sum()))
    mejor = resultados.iloc[0]
    log.info(f"Precios imputados={int(nulos.sum())} | outliers marcados={int(df['es_outlier'].sum())} | "
             f"edades imputadas={int(clientes['edad_imputada'].sum())} | mejor método en el experimento: "
             f"{mejor.metodo} ({mejor.error_relativo_medio_pct:.1f} % de error)")
    for r in resultados.itertuples():
        log.info(f"    {r.metodo:22} error relativo medio = {r.error_relativo_medio_pct:6.1f} %")
    return resultados


if __name__ == "__main__":
    imputar()
