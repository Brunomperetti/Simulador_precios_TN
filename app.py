import csv
import hashlib
from io import StringIO

import pandas as pd
import streamlit as st

# Columnas mínimas que necesita el simulador para trabajar con el CSV de Tienda Nube.
COLUMNAS_REQUERIDAS = ["Nombre", "Marca", "SKU", "Precio", "Costo"]
COLUMNAS_BASE_VISTA = [
    "Nombre",
    "Marca",
    "SKU",
    "Precio",
    "Costo",
    "Multiplicador actual",
    "Multiplicador",
    "Nuevo Precio",
]
COLUMNAS_ULTIMO_PRODUCTO = COLUMNAS_BASE_VISTA + ["Diferencia $", "Diferencia %"]
COLUMNAS_PRODUCTOS_MODIFICADOS = COLUMNAS_ULTIMO_PRODUCTO
COLUMNAS_BUSQUEDA_SIMULACION = COLUMNAS_ULTIMO_PRODUCTO


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


def calcular_multiplicador_actual(precio: pd.Series, costo: pd.Series) -> pd.Series:
    """Calcula Precio actual / Costo solo cuando el costo existe y es mayor a cero."""
    multiplicador_actual = precio / costo.where(costo.gt(0))
    return multiplicador_actual.replace([float("inf"), -float("inf")], pd.NA)


def tiene_costo_valido(costo: pd.Series) -> pd.Series:
    """Considera válido el costo numérico mayor a cero."""
    return costo.notna() & costo.gt(0)


def series_diferentes(actual: pd.Series, original: pd.Series) -> pd.Series:
    """Compara series considerando equivalentes los valores vacíos en ambas."""
    ambos_vacios = actual.isna() & original.isna()
    return actual.ne(original) & ~ambos_vacios


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
    df_trabajo = recalcular_precios(df_trabajo)

    return df_trabajo


def recalcular_precios(df_editado: pd.DataFrame) -> pd.DataFrame:
    """Recalcula el nuevo precio usando siempre Costo * Multiplicador."""
    df_calculado = df_editado.copy()

    df_calculado["Precio"] = pd.to_numeric(
        df_calculado["Precio"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Costo"] = pd.to_numeric(
        df_calculado["Costo"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Multiplicador"] = pd.to_numeric(
        df_calculado["Multiplicador"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Multiplicador actual"] = calcular_multiplicador_actual(
        df_calculado["Precio"], df_calculado["Costo"]
    )
    df_calculado["Nuevo Precio"] = df_calculado["Costo"] * df_calculado["Multiplicador"]

    return df_calculado[COLUMNAS_BASE_VISTA]


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


def calcular_mascara_modificados(
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set,
) -> pd.Series:
    """Marca como modificados solo productos editados o afectados por una acción explícita."""
    multiplicador_modificado = df_calculado["Multiplicador"].fillna(1).ne(1)
    costo_original = costos_originales.reindex(df_calculado.index)
    costo_editado = df_calculado["Costo"]
    costo_modificado = series_diferentes(costo_editado, costo_original)
    afectado_por_accion = pd.Series(
        df_calculado.index.isin(indices_afectados), index=df_calculado.index
    )

    return multiplicador_modificado | costo_modificado | afectado_por_accion


def preparar_vista_con_diferencias(df_calculado: pd.DataFrame) -> pd.DataFrame:
    """Agrega diferencias absolutas y porcentuales contra el precio actual."""
    df_vista = df_calculado.copy()
    df_vista["Diferencia $"] = df_vista["Nuevo Precio"] - df_vista["Precio"]
    df_vista["Diferencia %"] = (
        df_vista["Diferencia $"] / df_vista["Precio"].replace(0, pd.NA)
    ) * 100

    return df_vista


def preparar_vista_cambios(
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set,
) -> pd.DataFrame:
    """Prepara la tabla de productos realmente modificados."""
    df_cambios = preparar_vista_con_diferencias(df_calculado)
    mascara_modificados = calcular_mascara_modificados(
        df_cambios, costos_originales, indices_afectados
    )

    return df_cambios.loc[mascara_modificados, COLUMNAS_PRODUCTOS_MODIFICADOS]


def mostrar_resumen_cambios(
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set,
) -> None:
    """Muestra métricas principales para no revisar producto por producto."""
    productos_modificados = int(
        calcular_mascara_modificados(
            df_calculado, costos_originales, indices_afectados
        ).sum()
    )
    productos_sin_costo = int((~tiene_costo_valido(df_calculado["Costo"])).sum())
    multiplicadores_distintos = int(df_calculado["Multiplicador"].fillna(1).ne(1).sum())
    productos_sin_nuevo_precio = int(df_calculado["Nuevo Precio"].isna().sum())
    multiplicador_actual_promedio = df_calculado["Multiplicador actual"].mean()
    multiplicador_aplicado_promedio = df_calculado["Multiplicador"].mean()

    st.subheader("Resumen de cambios")
    fila_1 = st.columns(4)
    fila_2 = st.columns(3)
    fila_1[0].metric("Total de productos", len(df_calculado))
    fila_1[1].metric("Productos modificados", productos_modificados)
    fila_1[2].metric("Productos sin costo", productos_sin_costo)
    fila_1[3].metric("Multiplicador ≠ 1", multiplicadores_distintos)
    fila_2[0].metric("Nuevo precio vacío", productos_sin_nuevo_precio)
    fila_2[1].metric(
        "Multiplicador actual promedio",
        (
            "-"
            if pd.isna(multiplicador_actual_promedio)
            else f"{multiplicador_actual_promedio:.4f}"
        ),
    )
    fila_2[2].metric(
        "Multiplicador aplicado promedio",
        (
            "-"
            if pd.isna(multiplicador_aplicado_promedio)
            else f"{multiplicador_aplicado_promedio:.4f}"
        ),
    )


def mostrar_advertencias_exportacion(df_calculado: pd.DataFrame) -> None:
    """Advierte problemas que conviene resolver antes de descargar el CSV final."""
    productos_sin_costo = int((~tiene_costo_valido(df_calculado["Costo"])).sum())
    productos_sin_nuevo_precio = int(df_calculado["Nuevo Precio"].isna().sum())
    productos_precio_menor_costo = int(
        df_calculado["Nuevo Precio"].lt(df_calculado["Costo"]).sum()
    )
    productos_precio_menor_actual = int(
        df_calculado["Nuevo Precio"].lt(df_calculado["Precio"]).sum()
    )

    advertencias = []
    if productos_sin_costo:
        advertencias.append(f"{productos_sin_costo} productos sin costo")
    if productos_sin_nuevo_precio:
        advertencias.append(f"{productos_sin_nuevo_precio} productos sin nuevo precio")
    if productos_precio_menor_costo:
        advertencias.append(
            f"{productos_precio_menor_costo} productos con nuevo precio menor al costo"
        )
    if productos_precio_menor_actual:
        advertencias.append(
            f"{productos_precio_menor_actual} productos donde el precio simulado queda por debajo del precio publicado actual"
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


def obtener_config_columnas() -> dict:
    """Centraliza nombres y formatos de columnas para todas las vistas."""
    return {
        "Precio": st.column_config.NumberColumn("Precio actual", format="%.2f"),
        "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
        "Multiplicador actual": st.column_config.NumberColumn(
            "Multiplicador actual", format="%.4f"
        ),
        "Multiplicador": st.column_config.NumberColumn(
            "Multiplicador aplicado", min_value=0.0, step=0.1, format="%.4f"
        ),
        "Nuevo Precio": st.column_config.NumberColumn("Nuevo Precio", format="%.2f"),
        "Diferencia $": st.column_config.NumberColumn("Diferencia $", format="%.2f"),
        "Diferencia %": st.column_config.NumberColumn("Diferencia %", format="%.2f%%"),
    }


def colorear_filas_revision(df_vista: pd.DataFrame):
    """Colorea filas de revisión según precio simulado y costo disponible."""

    def estilo_fila(fila: pd.Series) -> list[str]:
        costo = fila.get("Costo")
        precio_actual = fila.get("Precio")
        nuevo_precio = fila.get("Nuevo Precio")

        if pd.isna(costo) or str(costo).strip() == "":
            color = "background-color: #fff3cd"
        elif (
            pd.notna(nuevo_precio)
            and pd.notna(precio_actual)
            and nuevo_precio > precio_actual
        ):
            color = "background-color: #d1e7dd"
        elif (
            pd.notna(nuevo_precio)
            and pd.notna(precio_actual)
            and nuevo_precio < precio_actual
        ):
            color = "background-color: #f8d7da"
        else:
            color = ""

        return [color] * len(fila)

    return df_vista.style.apply(estilo_fila, axis=1)


def mostrar_tabla_revision(df_vista: pd.DataFrame, config_columnas: dict) -> None:
    """Muestra una tabla de revisión con colores de ayuda visual."""
    st.dataframe(
        colorear_filas_revision(df_vista),
        use_container_width=True,
        hide_index=True,
        column_config=config_columnas,
    )


def actualizar_ultimo_producto(df_calculado: pd.DataFrame, indices_modificados) -> None:
    """Guarda el último producto afectado para mostrarlo con diferencias actualizadas."""
    indices_modificados = list(indices_modificados)
    if not indices_modificados:
        return

    ultimo_indice = indices_modificados[-1]
    st.session_state["ultimo_producto_modificado"] = preparar_vista_con_diferencias(
        df_calculado.loc[[ultimo_indice]]
    )[COLUMNAS_ULTIMO_PRODUCTO]


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
        tabla_inicial = preparar_tabla_trabajo(df)
        st.session_state["tabla_trabajo"] = tabla_inicial
        st.session_state["costos_originales"] = tabla_inicial["Costo"].copy()
        st.session_state["indices_afectados"] = set()
        st.session_state["archivo_id"] = archivo_id
        st.session_state["ultimo_producto_modificado"] = None
        st.session_state["editor_version"] = 0

    config_columnas = obtener_config_columnas()

    st.subheader("Multiplicador global")
    with st.form("multiplicador_global"):
        col_global, col_boton_global = st.columns([1, 2])
        multiplicador_global = col_global.number_input(
            "Multiplicador global",
            min_value=0.0,
            value=1.0,
            step=0.1,
            format="%.4f",
        )
        aplicar_global = col_boton_global.form_submit_button(
            "Aplicar a todos los productos con costo"
        )

    if aplicar_global:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        mascara_con_costo = tiene_costo_valido(tabla_actual["Costo"])
        indices_actualizados = tabla_actual.index[mascara_con_costo].tolist()
        tabla_actual.loc[mascara_con_costo, "Multiplicador"] = multiplicador_global
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_actualizados)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_actualizados)
        st.success(
            f"Multiplicador {multiplicador_global} aplicado a {len(indices_actualizados)} productos con costo."
        )

    st.subheader("Margen objetivo")
    with st.form("margen_objetivo"):
        col_margen, col_boton_margen = st.columns([1, 2])
        margen_objetivo = col_margen.number_input(
            "Margen objetivo (%)",
            min_value=0.0,
            value=0.0,
            step=1.0,
            format="%.2f",
        )
        aplicar_margen_objetivo = col_boton_margen.form_submit_button(
            "Aplicar margen objetivo a todos los productos con costo"
        )

    if aplicar_margen_objetivo:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        mascara_con_costo = tiene_costo_valido(tabla_actual["Costo"])
        indices_actualizados = tabla_actual.index[mascara_con_costo].tolist()
        productos_sin_costo = int((~mascara_con_costo).sum())
        multiplicador_margen = 1 + margen_objetivo / 100
        tabla_actual.loc[mascara_con_costo, "Multiplicador"] = multiplicador_margen
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_actualizados)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_actualizados)
        st.success(
            "Margen objetivo aplicado a "
            f"{len(indices_actualizados)} productos con costo válido. "
            f"{productos_sin_costo} productos quedaron sin modificar por no tener costo."
        )

    st.subheader("Restaurar simulación")
    st.write("Vuelve los multiplicadores a 1 y conserva los costos que hayas editado.")
    if st.button("Restaurar simulación"):
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        tabla_actual["Multiplicador"] = 1.0
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["costos_originales"] = tabla_actual["Costo"].copy()
        st.session_state["indices_afectados"] = set()
        st.session_state["ultimo_producto_modificado"] = None
        st.session_state["editor_version"] += 1
        st.success("Simulación restaurada. Se mantuvieron los costos editados.")

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
        indices_actualizados = tabla_actual.index[mascara_marca].tolist()
        tabla_actual.loc[mascara_marca, "Multiplicador"] = multiplicador_masivo
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_actualizados)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_actualizados)
        st.success(
            f"Multiplicador {multiplicador_masivo} aplicado a {len(indices_actualizados)} productos."
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
        st.session_state["indices_afectados"].add(producto_seleccionado)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, [producto_seleccionado])
        producto_aplicado = formatear_opcion_producto(
            tabla_actual.loc[producto_seleccionado]
        )
        st.success(
            f"Multiplicador {multiplicador_producto} aplicado al producto: {producto_aplicado}."
        )

    if st.session_state.get("ultimo_producto_modificado") is not None:
        st.subheader("Último producto modificado")
        mostrar_tabla_revision(
            st.session_state["ultimo_producto_modificado"], config_columnas
        )

    st.subheader("Editor de productos")
    st.write(
        "Podés editar **Costo** y **Multiplicador aplicado** por fila. "
        "Las demás columnas son solo de referencia."
    )

    tabla_previa_editor = st.session_state["tabla_trabajo"].copy()
    df_editado = st.data_editor(
        st.session_state["tabla_trabajo"],
        key=f"editor_productos_{st.session_state['editor_version']}",
        use_container_width=True,
        num_rows="fixed",
        disabled=[
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Multiplicador actual",
            "Nuevo Precio",
        ],
        column_config=config_columnas,
    )

    # Recalculamos siempre con los últimos valores editados para que el resultado y el CSV coincidan.
    df_calculado = recalcular_precios(df_editado)
    filas_editadas = df_calculado.index[
        series_diferentes(df_calculado["Costo"], tabla_previa_editor["Costo"])
        | series_diferentes(
            df_calculado["Multiplicador"], tabla_previa_editor["Multiplicador"]
        )
    ].tolist()
    actualizar_ultimo_producto(df_calculado, filas_editadas)
    st.session_state["tabla_trabajo"] = df_calculado

    costos_originales = st.session_state["costos_originales"]
    indices_afectados = st.session_state["indices_afectados"]
    mostrar_resumen_cambios(df_calculado, costos_originales, indices_afectados)

    st.subheader("Productos modificados")
    productos_modificados = preparar_vista_cambios(
        df_calculado, costos_originales, indices_afectados
    )
    if productos_modificados.empty:
        st.info("Todavía no hay productos modificados.")
    else:
        mostrar_tabla_revision(productos_modificados, config_columnas)

    st.subheader("Buscar producto en la simulación")
    busqueda_simulacion = st.text_input(
        "Buscar en la simulación por Nombre, SKU o Marca",
        key="busqueda_simulacion",
    )
    productos_encontrados = preparar_vista_con_diferencias(
        filtrar_productos(df_calculado, busqueda_simulacion)
    )[COLUMNAS_BUSQUEDA_SIMULACION]
    st.caption(f"Coincidencias: {len(productos_encontrados)}")
    mostrar_tabla_revision(productos_encontrados, config_columnas)

    st.subheader("Resultado calculado")
    mostrar_tabla_revision(df_calculado, config_columnas)

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
