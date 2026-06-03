import csv
import hashlib
from io import StringIO

import pandas as pd
import streamlit as st

# Columnas mínimas que necesita el simulador para trabajar con el CSV de Tienda Nube.
COLUMNAS_REQUERIDAS = ["Nombre", "Marca", "SKU", "Precio", "Costo"]


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

    if (
        "tabla_trabajo" not in st.session_state
        or st.session_state.get("archivo_id") != archivo_id
    ):
        st.session_state["tabla_trabajo"] = preparar_tabla_trabajo(df)
        st.session_state["archivo_id"] = archivo_id

    if aplicar_masivo and marcas:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        mascara_marca = tabla_actual["Marca"].astype(str) == str(marca_seleccionada)
        tabla_actual.loc[mascara_marca, "Multiplicador"] = multiplicador_masivo
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.success(
            f"Multiplicador {multiplicador_masivo} aplicado a {int(mascara_marca.sum())} productos."
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

    st.write(f"Productos cargados: **{len(df_calculado)}**")
    st.subheader("Resultado calculado")
    st.dataframe(df_calculado, use_container_width=True)

    # El dataframe final conserva todas las columnas originales y solo reemplaza la columna Precio.
    df_final = df.copy()
    df_final["Precio"] = df_calculado["Nuevo Precio"].map(formato_precio)

    st.subheader("Exportar CSV final")
    st.download_button(
        label="Descargar CSV para Tienda Nube",
        data=generar_csv_descarga(df_final, separador),
        file_name="tienda_nube_precios_actualizados.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
