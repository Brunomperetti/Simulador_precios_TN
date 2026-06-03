import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Simulador Tienda Nube",
    layout="wide"
)

st.title("Simulador de precios - Tienda Nube")

archivo = st.file_uploader(
    "Subí el CSV exportado desde Tienda Nube",
    type=["csv"]
)

if archivo is not None:
    df = pd.read_csv(
        archivo,
        encoding="latin1",
        sep=None,
        engine="python",
        on_bad_lines="skip"
    )

    st.success("CSV cargado correctamente")

    filas, columnas = df.shape

    st.write(f"Filas: **{filas}**")
    st.write(f"Columnas: **{columnas}**")

    st.subheader("Editor de productos")

    columnas_trabajo = [
        "Nombre",
        "Marca",
        "SKU",
        "Precio",
        "Costo"
    ]

    df_trabajo = df[columnas_trabajo].copy()

    # Limpiar columnas numéricas
    df_trabajo["Precio"] = pd.to_numeric(df_trabajo["Precio"], errors="coerce")
    df_trabajo["Costo"] = pd.to_numeric(df_trabajo["Costo"], errors="coerce")

    # Crear columnas de simulación
    df_trabajo["Multiplicador"] = 1.0
    df_trabajo["Nuevo Precio"] = df_trabajo["Costo"] * df_trabajo["Multiplicador"]

    df_editado = st.data_editor(
        df_trabajo,
        use_container_width=True,
        num_rows="fixed"
    )

    st.write(f"Productos cargados: {len(df_editado)}")

    if st.button("Calcular precios"):
        df_editado["Costo"] = pd.to_numeric(df_editado["Costo"], errors="coerce")
        df_editado["Multiplicador"] = pd.to_numeric(df_editado["Multiplicador"], errors="coerce")

        df_editado["Nuevo Precio"] = df_editado["Costo"] * df_editado["Multiplicador"]

        st.subheader("Resultado calculado")
        st.dataframe(df_editado, use_container_width=True)

else:
    st.info("Subí un archivo CSV para comenzar.")