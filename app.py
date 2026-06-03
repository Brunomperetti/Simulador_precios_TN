import csv
import hashlib
from io import StringIO

import pandas as pd
import streamlit as st

# Columnas mínimas que necesita el simulador para trabajar con el CSV de Tienda Nube.
COLUMNAS_REQUERIDAS = ["Nombre", "Marca", "SKU", "Precio", "Costo"]
COLUMNAS_ULTIMO_PRODUCTO = [
    "Nombre",
    "Marca",
    "SKU",
    "Precio",
    "Costo",
    "Multiplicador",
    "Nuevo Precio",
]
COLUMNAS_PRODUCTOS_MODIFICADOS = COLUMNAS_ULTIMO_PRODUCTO + [
    "Diferencia $",
    "Diferencia %",
]


def detectar_separador(contenido: bytes) -> str:
    """Detecta el separador del CSV para exportar con el mismo formato base."""
    muestra = contenido[:4096].decode("utf-8-sig", errors="replace")

    try:
        return csv.Sniffer().sniff(muestra, delimiters=[",", ";", "\t", "|"]).delimiter
    except csv.Error:
        # Tienda Nube suele exportar CSV con coma o punto y coma; si no se detecta, usamos coma.
        return ","


def leer_csv(contenido: bytes, separador: str) -> pd.DataFrame:
    """Lee el CSV probando codificaciones habituales de exportaciones de tiendas."""
    ultimo_error = None

    for encoding in ("utf-8-sig", "utf-8", "latin1"):
        try:
            return pd.read_csv(
                StringIO(contenido.decode(encoding)),
                sep=separador,
                dtype=str,
                keep_default_na=False,
            )
        except UnicodeDecodeError as error:
            ultimo_error = error

    raise ultimo_error


def normalizar_numero(valor) -> float:
    """
    Convierte números escritos con comas o puntos a float.

    Ejemplos válidos:
    - "1234.56"
    - "1234,56"
    - "1.234,56"
    - "1,234.56"
    - valores vacíos, que se convierten en NA.
    """
    if pd.isna(valor):
        return pd.NA

    texto = str(valor).strip()
    if texto == "":
        return pd.NA

    # Quitamos símbolos comunes sin perder separadores decimales o signo negativo.
    texto = (
        texto.replace("$", "").replace(" ", "").replace("\u00a0", "").replace("'", "")
    )

    tiene_coma = "," in texto
    tiene_punto = "." in texto

    if tiene_coma and tiene_punto:
        # El separador decimal suele ser el último símbolo entre coma y punto.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif tiene_coma:
        partes = texto.split(",")
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            texto = texto.replace(",", "")
        else:
            texto = texto.replace(",", ".")
    elif tiene_punto:
        partes = texto.split(".")
        if len(partes) > 1 and all(len(parte) == 3 for parte in partes[1:]):
            texto = texto.replace(".", "")

    return pd.to_numeric(texto, errors="coerce")


def preparar_tabla_trabajo(df_original: pd.DataFrame) -> pd.DataFrame:
    """Crea la tabla editable sin modificar todavía el dataframe original."""
    df_trabajo = df_original[COLUMNAS_REQUERIDAS].copy()

    df_trabajo["Precio"] = pd.to_numeric(
        df_trabajo["Precio"].map(normalizar_numero), errors="coerce"
    )
    df_trabajo["Costo"] = pd.to_numeric(
        df_trabajo["Costo"].map(normalizar_numero), errors="coerce"
    )
    df_trabajo["Multiplicador"] = 1.0
    df_trabajo["Nuevo Precio"] = df_trabajo["Costo"] * df_trabajo["Multiplicador"]

    return df_trabajo


def recalcular_precios(df_editado: pd.DataFrame) -> pd.DataFrame:
    """Recalcula el nuevo precio usando los costos y multiplicadores editados."""
    df_calculado = df_editado.copy()

    df_calculado["Costo"] = pd.to_numeric(
        df_calculado["Costo"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Multiplicador"] = pd.to_numeric(
        df_calculado["Multiplicador"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Nuevo Precio"] = df_calculado["Costo"] * df_calculado["Multiplicador"]

    return df_calculado


def formatear_opcion_producto(fila: pd.Series) -> str:
    """Muestra cada producto como Nombre | SKU | Marca para el selector."""
    nombre = str(fila.get("Nombre", "")).strip()
    sku = str(fila.get("SKU", "")).strip()
    marca = str(fila.get("Marca", "")).strip()

    return f"{nombre} | {sku} | {marca}"


def filtrar_productos(df_trabajo: pd.DataFrame, busqueda: str) -> pd.DataFrame:
    """Filtra productos por texto contenido en Nombre, SKU o Marca."""
    texto = busqueda.strip().lower()
    if not texto:
        return df_trabajo

    mascara = pd.Series(False, index=df_trabajo.index)
    for columna in ("Nombre", "SKU", "Marca"):
        mascara |= (
            df_trabajo[columna]
            .astype(str)
            .str.lower()
            .str.contains(texto, na=False, regex=False)
        )

    return df_trabajo[mascara]


def calcular_mascara_modificados(df_calculado: pd.DataFrame) -> pd.Series:
    """Identifica filas con multiplicador aplicado o precio final diferente al actual."""
    multiplicador_modificado = df_calculado["Multiplicador"].fillna(1).ne(1)
    precio_actual = df_calculado["Precio"]
    nuevo_precio = df_calculado["Nuevo Precio"]
    precio_diferente = precio_actual.ne(nuevo_precio) | precio_actual.isna().ne(
        nuevo_precio.isna()
    )

    return multiplicador_modificado | precio_diferente


def preparar_vista_cambios(df_calculado: pd.DataFrame) -> pd.DataFrame:
    """Agrega diferencias para revisar rápidamente los productos modificados."""
    df_cambios = df_calculado.copy()
    df_cambios["Diferencia $"] = df_cambios["Nuevo Precio"] - df_cambios["Precio"]
    df_cambios["Diferencia %"] = (
        df_cambios["Diferencia $"] / df_cambios["Precio"].replace(0, pd.NA)
    ) * 100

    return df_cambios.loc[
        calcular_mascara_modificados(df_cambios), COLUMNAS_PRODUCTOS_MODIFICADOS
    ]


def mostrar_resumen_cambios(df_calculado: pd.DataFrame) -> None:
    """Muestra métricas principales para no revisar producto por producto."""
    productos_modificados = int(calcular_mascara_modificados(df_calculado).sum())
    productos_sin_costo = int(df_calculado["Costo"].isna().sum())
    multiplicadores_distintos = int(df_calculado["Multiplicador"].fillna(1).ne(1).sum())
    productos_sin_nuevo_precio = int(df_calculado["Nuevo Precio"].isna().sum())

    st.subheader("Resumen de cambios")
    col_total, col_modificados, col_sin_costo, col_multiplicador, col_sin_precio = (
        st.columns(5)
    )
    col_total.metric("Total de productos", len(df_calculado))
    col_modificados.metric("Productos modificados", productos_modificados)
    col_sin_costo.metric("Productos sin costo", productos_sin_costo)
    col_multiplicador.metric("Multiplicador ≠ 1", multiplicadores_distintos)
    col_sin_precio.metric("Nuevo precio vacío", productos_sin_nuevo_precio)


def mostrar_advertencias_exportacion(df_calculado: pd.DataFrame) -> None:
    """Advierte problemas que conviene resolver antes de descargar el CSV final."""
    productos_sin_costo = int(df_calculado["Costo"].isna().sum())
    productos_sin_nuevo_precio = int(df_calculado["Nuevo Precio"].isna().sum())
    precio_menor_costo = df_calculado["Nuevo Precio"].lt(df_calculado["Costo"])
    productos_precio_menor_costo = int(precio_menor_costo.sum())

    advertencias = []
    if productos_sin_costo:
        advertencias.append(f"{productos_sin_costo} productos sin costo")
    if productos_sin_nuevo_precio:
        advertencias.append(f"{productos_sin_nuevo_precio} productos sin nuevo precio")
    if productos_precio_menor_costo:
        advertencias.append(
            f"{productos_precio_menor_costo} productos con nuevo precio menor al costo"
        )

    if advertencias:
        st.warning("Antes de exportar, revisá: " + "; ".join(advertencias) + ".")
    else:
        st.success("Control de exportación OK: no se detectaron problemas.")


def formato_precio(valor) -> str:
    """Formatea el precio para el CSV final evitando valores 'nan'."""
    if pd.isna(valor):
        return ""

    numero = float(valor)
    if numero.is_integer():
        return str(int(numero))

    return f"{numero:.2f}"


def generar_csv_descarga(df_final: pd.DataFrame, separador: str) -> bytes:
    """Exporta con utf-8-sig para que Excel y Tienda Nube lean bien acentos y ñ."""
    return df_final.to_csv(index=False, sep=separador, encoding="utf-8-sig").encode(
        "utf-8-sig"
    )


def main() -> None:
    """Renderiza la aplicación Streamlit."""
    st.set_page_config(page_title="Simulador Tienda Nube", layout="wide")
    st.title("Simulador de precios - Tienda Nube")
    st.caption(
        "Subí un CSV exportado desde Tienda Nube, editá costos y multiplicadores, "
        "y descargá el archivo final manteniendo intactas las demás columnas."
    )

    archivo = st.file_uploader("Subí el CSV exportado desde Tienda Nube", type=["csv"])

    if archivo is None:
        st.info("Subí un archivo CSV para comenzar.")
        st.stop()

    contenido = archivo.getvalue()
    archivo_id = hashlib.sha256(contenido).hexdigest()
    separador = detectar_separador(contenido)

    try:
        df = leer_csv(contenido, separador)
    except Exception as error:
        st.error(
            f"No se pudo leer el CSV. Revisá el archivo e intentá nuevamente. Detalle: {error}"
        )
        st.stop()

    st.success("CSV cargado correctamente")
    st.write(f"Filas: **{df.shape[0]}**")
    st.write(f"Columnas: **{df.shape[1]}**")
    st.write(f"Separador detectado: **{repr(separador)}**")

    columnas_faltantes = [
        columna for columna in COLUMNAS_REQUERIDAS if columna not in df.columns
    ]
    if columnas_faltantes:
        st.error(
            "El CSV no tiene todas las columnas requeridas. "
            f"Faltan: {', '.join(columnas_faltantes)}."
        )
        st.stop()

    # Guardamos una tabla de trabajo por archivo para conservar cambios entre interacciones.
    if (
        "tabla_trabajo" not in st.session_state
        or st.session_state.get("archivo_id") != archivo_id
    ):
        st.session_state["tabla_trabajo"] = preparar_tabla_trabajo(df)
        st.session_state["archivo_id"] = archivo_id
        st.session_state["ultimo_producto_modificado"] = None

    st.subheader("Multiplicador masivo por marca")
    marcas = sorted(
        marca for marca in df["Marca"].dropna().astype(str).unique() if marca.strip()
    )

    with st.form("multiplicador_masivo"):
        col_marca, col_multiplicador = st.columns([2, 1])
        marca_seleccionada = col_marca.selectbox(
            "Marca", options=marcas, disabled=not marcas
        )
        multiplicador_masivo = col_multiplicador.number_input(
            "Multiplicador",
            min_value=0.0,
            value=1.0,
            step=0.1,
            format="%.4f",
        )
        aplicar_masivo = st.form_submit_button("Aplicar a la marca")

    if aplicar_masivo and marcas:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        mascara_marca = tabla_actual["Marca"].astype(str) == str(marca_seleccionada)
        tabla_actual.loc[mascara_marca, "Multiplicador"] = multiplicador_masivo
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.success(
            f"Multiplicador {multiplicador_masivo} aplicado a {int(mascara_marca.sum())} productos."
        )

    st.subheader("Multiplicador por producto")
    st.write(
        "Buscá por **Nombre**, **SKU** o **Marca** y aplicá el cambio solo al producto elegido."
    )

    busqueda_producto = st.text_input("Buscar producto por Nombre, SKU o Marca")
    productos_filtrados = filtrar_productos(
        st.session_state["tabla_trabajo"], busqueda_producto
    )
    opciones_productos = list(productos_filtrados.index)
    etiquetas_productos = {
        indice: formatear_opcion_producto(fila)
        for indice, fila in productos_filtrados.iterrows()
    }

    with st.form("multiplicador_producto"):
        col_producto, col_multiplicador_producto = st.columns([3, 1])
        producto_seleccionado = col_producto.selectbox(
            "Producto",
            options=opciones_productos,
            format_func=lambda indice: etiquetas_productos.get(indice, ""),
            disabled=not opciones_productos,
        )
        multiplicador_producto = col_multiplicador_producto.number_input(
            "Multiplicador del producto",
            min_value=0.0,
            value=1.0,
            step=0.1,
            format="%.4f",
        )
        aplicar_producto = st.form_submit_button(
            "Aplicar al producto", disabled=not opciones_productos
        )

    if not opciones_productos:
        st.info("No se encontraron productos para la búsqueda ingresada.")

    if aplicar_producto and opciones_productos:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        tabla_actual.loc[producto_seleccionado, "Multiplicador"] = (
            multiplicador_producto
        )
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["ultimo_producto_modificado"] = tabla_actual.loc[
            [producto_seleccionado], COLUMNAS_ULTIMO_PRODUCTO
        ]
        producto_aplicado = formatear_opcion_producto(
            tabla_actual.loc[producto_seleccionado]
        )
        st.success(
            f"Multiplicador {multiplicador_producto} aplicado al producto: {producto_aplicado}."
        )

    if st.session_state.get("ultimo_producto_modificado") is not None:
        st.subheader("Último producto modificado")
        st.dataframe(
            st.session_state["ultimo_producto_modificado"],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Precio": st.column_config.NumberColumn("Precio actual", format="%.2f"),
                "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
                "Multiplicador": st.column_config.NumberColumn(
                    "Multiplicador", format="%.4f"
                ),
                "Nuevo Precio": st.column_config.NumberColumn(
                    "Nuevo Precio", format="%.2f"
                ),
            },
        )

    st.subheader("Editor de productos")
    st.write(
        "Podés editar **Costo** y **Multiplicador** por fila. Las demás columnas son solo de referencia."
    )

    df_editado = st.data_editor(
        st.session_state["tabla_trabajo"],
        key="editor_productos",
        use_container_width=True,
        num_rows="fixed",
        disabled=["Nombre", "Marca", "SKU", "Precio", "Nuevo Precio"],
        column_config={
            "Precio": st.column_config.NumberColumn("Precio actual", format="%.2f"),
            "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
            "Multiplicador": st.column_config.NumberColumn(
                "Multiplicador", min_value=0.0, step=0.1, format="%.4f"
            ),
            "Nuevo Precio": st.column_config.NumberColumn(
                "Nuevo Precio", format="%.2f"
            ),
        },
    )

    # Recalculamos siempre con los últimos valores editados para que el resultado y el CSV coincidan.
    df_calculado = recalcular_precios(df_editado)
    st.session_state["tabla_trabajo"] = df_calculado

    mostrar_resumen_cambios(df_calculado)

    st.subheader("Productos modificados")
    productos_modificados = preparar_vista_cambios(df_calculado)
    if productos_modificados.empty:
        st.info("Todavía no hay productos modificados.")
    else:
        st.dataframe(
            productos_modificados,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Precio": st.column_config.NumberColumn("Precio actual", format="%.2f"),
                "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
                "Multiplicador": st.column_config.NumberColumn(
                    "Multiplicador", format="%.4f"
                ),
                "Nuevo Precio": st.column_config.NumberColumn(
                    "Nuevo Precio", format="%.2f"
                ),
                "Diferencia $": st.column_config.NumberColumn(
                    "Diferencia $", format="%.2f"
                ),
                "Diferencia %": st.column_config.NumberColumn(
                    "Diferencia %", format="%.2f%%"
                ),
            },
        )

    st.subheader("Buscar producto en la simulación")
    busqueda_simulacion = st.text_input(
        "Buscar en la simulación por Nombre, SKU o Marca",
        key="busqueda_simulacion",
    )
    productos_encontrados = filtrar_productos(df_calculado, busqueda_simulacion)
    st.caption(f"Coincidencias: {len(productos_encontrados)}")
    st.dataframe(
        productos_encontrados,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Precio": st.column_config.NumberColumn("Precio actual", format="%.2f"),
            "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
            "Multiplicador": st.column_config.NumberColumn(
                "Multiplicador", format="%.4f"
            ),
            "Nuevo Precio": st.column_config.NumberColumn(
                "Nuevo Precio", format="%.2f"
            ),
        },
    )

    st.subheader("Resultado calculado")
    st.dataframe(df_calculado, use_container_width=True)

    # El dataframe final conserva todas las columnas originales y solo actualiza Precio y Costo.
    df_final = df.copy()
    df_final["Precio"] = df_calculado["Nuevo Precio"].map(formato_precio)
    df_final["Costo"] = df_calculado["Costo"].map(formato_precio)

    st.subheader("Exportar CSV final")
    mostrar_advertencias_exportacion(df_calculado)
    st.download_button(
        label="Descargar CSV para Tienda Nube",
        data=generar_csv_descarga(df_final, separador),
        file_name="tienda_nube_precios_actualizados.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
