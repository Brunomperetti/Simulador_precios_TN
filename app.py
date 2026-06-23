import csv
import hashlib
from datetime import date
from io import BytesIO, StringIO
from numbers import Real
from pathlib import Path
import re

import pandas as pd
import streamlit as st

# Columnas mínimas que necesita el simulador para trabajar con el CSV de Tienda Nube.
COLUMNAS_REQUERIDAS = ["Nombre", "Marca", "SKU", "Precio", "Costo"]
COLUMNA_IDENTIFICADOR_URL = "Identificador de URL"
COLUMNAS_VARIANTES = [
    "Identificador de URL",
    "Nombre",
    "Marca",
    "SKU",
    "Nombre de propiedad 1",
    "Valor de propiedad 1",
    "Nombre de propiedad 2",
    "Valor de propiedad 2",
    "Nombre de propiedad 3",
    "Valor de propiedad 3",
    "Precio",
    "Costo",
]
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
COLUMNAS_REVISION = COLUMNAS_BASE_VISTA + ["Estado", "Diferencia $", "Diferencia %"]
COLUMNAS_ULTIMO_PRODUCTO = COLUMNAS_REVISION
COLUMNAS_PRODUCTOS_MODIFICADOS = COLUMNAS_REVISION
COLUMNAS_BUSQUEDA_SIMULACION = COLUMNAS_REVISION
COLUMNAS_RESULTADO_CALCULADO = COLUMNAS_REVISION
REFERENCIA_ESTADOS = (
    "Referencia: 🟢 Sube precio | 🔴 Baja precio | 🟡 Sin costo | "
    "⚪ Sin modificar / sin cambios"
)
LIMITE_VISTA_PREVIA = 50
COLUMNAS_LISTA_PRECIOS = [
    "Nombre",
    "Marca",
    "SKU",
    "Costo",
    "Precio Minorista",
    "Precio Mayorista",
]
PIE_PDF_LISTA_PRECIOS = (
    "Precios sin IVA. Consultar por volúmenes superiores a $1.000.000. "
    "Forma de pago: transferencia o efectivo. Transporte a cargo del comprador."
)
LOGO_KIKI_PREDETERMINADO = Path("assets/logo_kiki.png")

TIPOS_PRODUCTO_LISTAS = ["Todos", "Alimentos", "Suplementos"]
MARCAS_SUPLEMENTOS_LISTAS = {
    "GEONAT",
    "PROVEFARMA",
    "VITAMIN WAY",
    "LABORATORIOS PHARMAMERICAN",
    "HORBAACH",
    "NATURAL LIFE",
    "NATUFARMA",
    "GENEO",
    "EXTENSION LIFE",
    "SUNDANCE",
    "NATURES TRUTH",
    "COLABELLA",
    "NEW GARDEN",
    "BLACK MACA",
    "CRINWAY",
    "SRI SRI TATTVA",
    "NATURE MADE",
}


def detectar_separador(contenido: bytes) -> str:
    """Detecta el separador del CSV para exportar con el mismo formato base."""
    muestra = contenido[:4096].decode("utf-8-sig", errors="replace")

    try:
        return csv.Sniffer().sniff(muestra, delimiters=[",", ";", "\t", "|"]).delimiter
    except csv.Error:
        # Tienda Nube suele exportar CSV con coma o punto y coma; si no se detecta, usamos coma.
        return ","


def detectar_codificacion(contenido: bytes) -> str:
    """Detecta una codificación compatible para leer y reexportar el CSV sin BOM."""
    if contenido.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    for encoding in ("utf-8", "latin1"):
        try:
            contenido.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue

    return "utf-8"


def normalizar_codificacion_exportacion(encoding: str | None) -> str:
    """Evita escribir BOM aunque el CSV original se haya leído con utf-8-sig."""
    if not encoding:
        return "utf-8"

    if encoding.lower().replace("_", "-") == "utf-8-sig":
        return "utf-8"

    return encoding


def leer_csv(
    contenido: bytes, separador: str, encoding: str | None = None
) -> pd.DataFrame:
    """Lee el CSV probando codificaciones habituales de exportaciones de tiendas."""
    ultimo_error = None
    codificaciones = [encoding] if encoding else []
    codificaciones.extend(
        candidato
        for candidato in ("utf-8-sig", "utf-8", "latin1")
        if candidato not in codificaciones
    )

    for encoding in codificaciones:
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
    Convierte números escritos con comas o puntos a float real.

    Ejemplos válidos:
    - "1234.56"
    - "1234,56"
    - "1.234,56"
    - "1,234.56"
    - valores numéricos ya calculados, que se preservan como float.
    - valores vacíos, que se convierten en NA.
    """
    if pd.isna(valor):
        return pd.NA

    if isinstance(valor, Real) and not isinstance(valor, bool):
        return float(valor)

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


def calcular_mascara_precios_actualizados(
    df_calculado: pd.DataFrame, indices_afectados: set | None = None
) -> pd.Series:
    """Marca filas cuyo precio final existe y cambia respecto del precio original."""
    precio_actual = pd.to_numeric(df_calculado["Precio"], errors="coerce")
    nuevo_precio = pd.to_numeric(df_calculado["Nuevo Precio"], errors="coerce")
    precio_cambia = series_diferentes(nuevo_precio, precio_actual)
    precio_actualizable = nuevo_precio.notna() & precio_cambia

    if indices_afectados is None:
        return precio_actualizable

    afectado_por_accion = pd.Series(
        df_calculado.index.isin(indices_afectados), index=df_calculado.index
    )
    return precio_actualizable & afectado_por_accion


def calcular_resumen_aplicacion(
    df_calculado: pd.DataFrame, indices_afectados
) -> dict[str, int]:
    """Cuenta alcance, precios realmente actualizados y productos sin costo válido."""
    indices = list(indices_afectados)
    afectados = pd.Series(df_calculado.index.isin(indices), index=df_calculado.index)
    sin_costo_valido = afectados & ~tiene_costo_valido(df_calculado["Costo"])
    precios_actualizados = calcular_mascara_precios_actualizados(
        df_calculado, set(indices)
    )

    return {
        "afectados": int(afectados.sum()),
        "precios_actualizados": int(precios_actualizados.sum()),
        "sin_costo_valido": int(sin_costo_valido.sum()),
    }


def construir_mensaje_aplicacion(
    prefijo: str, df_calculado: pd.DataFrame, indices_afectados, alcance: str
) -> str:
    """Construye mensajes claros para acciones masivas o por producto."""
    resumen = calcular_resumen_aplicacion(df_calculado, indices_afectados)
    return (
        f"{prefijo} aplicado a {resumen['afectados']} productos {alcance}. "
        f"{resumen['precios_actualizados']} precios fueron actualizados. "
        f"{resumen['sin_costo_valido']} productos quedaron sin modificar "
        "por no tener costo válido."
    )


def calcular_mascara_modificados(
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set,
) -> pd.Series:
    """Marca solo filas con precio final cambiado o costo editado."""
    costo_original = costos_originales.reindex(df_calculado.index)
    costo_editado = df_calculado["Costo"]
    costo_modificado = series_diferentes(costo_editado, costo_original)
    multiplicador_modificado = df_calculado["Multiplicador"].fillna(1).ne(1)
    afectado_por_accion = pd.Series(
        df_calculado.index.isin(indices_afectados), index=df_calculado.index
    )
    candidato_a_actualizar_precio = (
        afectado_por_accion | multiplicador_modificado | costo_modificado
    )
    precio_actualizado = (
        calcular_mascara_precios_actualizados(df_calculado)
        & candidato_a_actualizar_precio
    )

    return precio_actualizado | costo_modificado


def obtener_estado_revision(fila: pd.Series, modificado: bool) -> str:
    """Describe el estado visual de una fila según si fue modificada explícitamente."""
    if not modificado:
        return "⚪ Sin modificar"

    costo = fila.get("Costo")
    precio_actual = fila.get("Precio")
    nuevo_precio = fila.get("Nuevo Precio")

    if pd.isna(costo) or str(costo).strip() == "" or pd.isna(nuevo_precio):
        return "🟡 Sin costo"
    if pd.notna(precio_actual) and nuevo_precio > precio_actual:
        return "🟢 Sube precio"
    if pd.notna(precio_actual) and nuevo_precio < precio_actual:
        return "🔴 Baja precio"

    return "⚪ Sin cambios"


def preparar_vista_con_diferencias(
    df_calculado: pd.DataFrame,
    mascara_modificados: pd.Series | None = None,
) -> pd.DataFrame:
    """Agrega estado y diferencias contra el precio actual para revisar cambios."""
    df_vista = df_calculado.copy()
    if mascara_modificados is None:
        mascara_modificados = pd.Series(False, index=df_vista.index)
    else:
        mascara_modificados = mascara_modificados.reindex(
            df_vista.index, fill_value=False
        )

    df_vista["Estado"] = [
        obtener_estado_revision(fila, bool(mascara_modificados.loc[indice]))
        for indice, fila in df_vista.iterrows()
    ]
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
    mascara_modificados = calcular_mascara_modificados(
        df_calculado, costos_originales, indices_afectados
    )
    df_cambios = preparar_vista_con_diferencias(df_calculado, mascara_modificados)

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


def mostrar_advertencias_exportacion(
    df_calculado: pd.DataFrame, mascara_modificados: pd.Series
) -> None:
    """Advierte problemas que conviene resolver antes de descargar el CSV final."""
    mascara_modificados = mascara_modificados.reindex(
        df_calculado.index, fill_value=False
    )
    productos_sin_costo = int((~tiene_costo_valido(df_calculado["Costo"])).sum())
    productos_sin_nuevo_precio = int(df_calculado["Nuevo Precio"].isna().sum())
    productos_precio_menor_costo = int(
        df_calculado["Nuevo Precio"].lt(df_calculado["Costo"]).sum()
    )
    productos_modificados_menor_actual = int(
        (
            df_calculado["Nuevo Precio"].lt(df_calculado["Precio"])
            & mascara_modificados
        ).sum()
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
    if productos_modificados_menor_actual:
        advertencias.append(
            f"{productos_modificados_menor_actual} productos modificados quedan por debajo del precio publicado actual"
        )

    if advertencias:
        st.warning("Antes de exportar, revisá: " + "; ".join(advertencias) + ".")
    else:
        st.success("Control de exportación OK: no se detectaron problemas.")


def formatear_numero_tienda_nube(valor) -> str:
    """Formatea números para Tienda Nube: miles con coma y decimal con punto."""
    if pd.isna(valor):
        return ""

    return f"{float(valor):,.2f}"


def calcular_mascara_precios_exportados(
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set | None = None,
) -> pd.Series:
    """Marca precios que fueron afectados, son válidos y cambian realmente."""
    if indices_afectados is None:
        indices_afectados = set()

    return calcular_mascara_modificados(
        df_calculado, costos_originales, indices_afectados
    ) & calcular_mascara_precios_actualizados(df_calculado)


def construir_dataframe_exportacion_precios(
    df_original: pd.DataFrame,
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set | None = None,
) -> pd.DataFrame:
    """Conserva el dataframe original y modifica Precio y Costo afectados."""
    return construir_dataframe_exportacion(
        df_original, df_calculado, costos_originales, indices_afectados
    )


def construir_dataframe_exportacion(
    df_original: pd.DataFrame,
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    indices_afectados: set | None = None,
) -> pd.DataFrame:
    """Conserva columnas originales y actualiza Precio y Costo modificados."""
    df_final = df_original.copy()
    if indices_afectados is None:
        indices_afectados = set()

    mascara_actualizar_precio = calcular_mascara_precios_exportados(
        df_calculado, costos_originales, indices_afectados
    )
    mascara_actualizar_costo = series_diferentes(
        df_calculado["Costo"], costos_originales.reindex(df_calculado.index)
    )

    nuevos_precios = pd.to_numeric(df_calculado["Nuevo Precio"], errors="coerce")
    precios_exportados = df_original["Precio"].copy()
    precios_exportados.loc[mascara_actualizar_precio] = nuevos_precios.loc[
        mascara_actualizar_precio
    ].map(formatear_numero_tienda_nube)
    df_final["Precio"] = precios_exportados

    nuevos_costos = pd.to_numeric(df_calculado["Costo"], errors="coerce")
    costos_exportados = df_original["Costo"].copy()
    costos_exportados.loc[mascara_actualizar_costo] = nuevos_costos.loc[
        mascara_actualizar_costo
    ].map(formatear_numero_tienda_nube)
    df_final["Costo"] = costos_exportados

    return df_final


def separar_salto_linea(linea: str) -> tuple[str, str]:
    """Separa el contenido del registro de su salto de línea original."""
    if linea.endswith("\r\n"):
        return linea[:-2], "\r\n"
    if linea.endswith("\n") or linea.endswith("\r"):
        return linea[:-1], linea[-1]
    return linea, ""


def obtener_spans_campos_csv(linea: str, separador: str) -> list[tuple[int, int]]:
    """Devuelve posiciones de campos CSV sin reserializar la línea original."""
    contenido, _ = separar_salto_linea(linea)
    spans = []
    inicio = 0
    en_comillas = False
    indice = 0

    while indice < len(contenido):
        caracter = contenido[indice]
        if caracter == '"':
            if (
                en_comillas
                and indice + 1 < len(contenido)
                and contenido[indice + 1] == '"'
            ):
                indice += 2
                continue
            en_comillas = not en_comillas
        elif caracter == separador and not en_comillas:
            spans.append((inicio, indice))
            inicio = indice + 1
        indice += 1

    spans.append((inicio, len(contenido)))
    return spans


def reemplazar_campo_csv_preservando_linea(
    linea: str, separador: str, indice_columna: int, nuevo_valor: str
) -> str:
    """Reemplaza un único campo manteniendo intacto el resto del registro."""
    contenido, salto_linea = separar_salto_linea(linea)
    spans = obtener_spans_campos_csv(linea, separador)
    if indice_columna >= len(spans):
        return linea

    inicio, fin = spans[indice_columna]
    campo_original = contenido[inicio:fin]
    campo_izquierda = campo_original.lstrip()
    espacios_iniciales = campo_original[: len(campo_original) - len(campo_izquierda)]
    campo_derecha = campo_izquierda.rstrip()
    espacios_finales = campo_izquierda[len(campo_derecha) :]

    if campo_derecha.startswith('"') and campo_derecha.endswith('"'):
        nuevo_campo = f'{espacios_iniciales}"{nuevo_valor.replace(chr(34), chr(34) * 2)}"{espacios_finales}'
    else:
        nuevo_campo = f"{espacios_iniciales}{nuevo_valor}{espacios_finales}"

    return contenido[:inicio] + nuevo_campo + contenido[fin:] + salto_linea


def generar_csv_descarga_preservando_original(
    contenido_original: bytes,
    df_original: pd.DataFrame,
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    separador: str,
    encoding: str | None = None,
    indices_afectados: set | None = None,
) -> bytes:
    """
    Exporta usando el CSV subido como base y cambia Precio y Costo en filas modificadas.

    A diferencia de pandas.to_csv, esta función conserva encabezado, columnas, comillas,
    orden, separador, saltos de línea y filas no modificadas byte a byte siempre que la
    codificación original pueda reutilizarse.
    """
    encoding_lectura = encoding or detectar_codificacion(contenido_original)
    texto_original = contenido_original.decode(encoding_lectura)
    lineas = texto_original.splitlines(keepends=True)
    if not lineas:
        return contenido_original

    indice_precio = list(df_original.columns).index("Precio")
    indice_costo = list(df_original.columns).index("Costo")
    if indices_afectados is None:
        indices_afectados = set()

    mascara_actualizar_precio = calcular_mascara_precios_exportados(
        df_calculado, costos_originales, indices_afectados
    )
    mascara_actualizar_costo = series_diferentes(
        df_calculado["Costo"], costos_originales.reindex(df_calculado.index)
    )
    nuevos_precios = pd.to_numeric(df_calculado["Nuevo Precio"], errors="coerce")
    precios_por_indice = nuevos_precios.loc[mascara_actualizar_precio].map(
        formatear_numero_tienda_nube
    )
    nuevos_costos = pd.to_numeric(df_calculado["Costo"], errors="coerce")
    costos_por_indice = nuevos_costos.loc[mascara_actualizar_costo].map(
        formatear_numero_tienda_nube
    )

    lineas_exportadas = lineas.copy()
    for posicion, indice_df in enumerate(df_original.index, start=1):
        if posicion >= len(lineas_exportadas):
            continue
        if indice_df in precios_por_indice.index:
            lineas_exportadas[posicion] = reemplazar_campo_csv_preservando_linea(
                lineas_exportadas[posicion],
                separador,
                indice_precio,
                precios_por_indice.loc[indice_df],
            )
        if indice_df in costos_por_indice.index:
            lineas_exportadas[posicion] = reemplazar_campo_csv_preservando_linea(
                lineas_exportadas[posicion],
                separador,
                indice_costo,
                costos_por_indice.loc[indice_df],
            )

    return "".join(lineas_exportadas).encode(encoding_lectura)


def obtener_metricas_csv(df: pd.DataFrame) -> tuple[int, int | None, int | None]:
    """Devuelve filas, productos únicos por URL y filas repetidas/variantes."""
    filas_csv = int(df.shape[0])
    if COLUMNA_IDENTIFICADOR_URL not in df.columns:
        return filas_csv, None, None

    productos_unicos = int(df[COLUMNA_IDENTIFICADOR_URL].astype(str).nunique())
    variantes_repetidas = filas_csv - productos_unicos
    return filas_csv, productos_unicos, variantes_repetidas


def obtener_productos_con_variantes(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve filas cuyo Identificador de URL aparece más de una vez."""
    columnas_disponibles = [
        columna for columna in COLUMNAS_VARIANTES if columna in df.columns
    ]
    if COLUMNA_IDENTIFICADOR_URL not in df.columns:
        return pd.DataFrame(columns=columnas_disponibles)

    identificadores = df[COLUMNA_IDENTIFICADOR_URL].astype(str).str.strip()
    mascara_variantes = identificadores.ne("") & identificadores.duplicated(keep=False)
    return df.loc[mascara_variantes, columnas_disponibles]


def mostrar_productos_con_variantes(df: pd.DataFrame) -> None:
    """Muestra la sección que individualiza variantes/filas repetidas."""
    st.subheader("Productos con variantes")
    productos_con_variantes = obtener_productos_con_variantes(df)

    if productos_con_variantes.empty:
        st.info("No se detectaron productos con variantes.")
        return

    st.write(
        "Estas filas no son errores: Tienda Nube usa más de una fila cuando un producto tiene variantes."
    )
    st.dataframe(productos_con_variantes, use_container_width=True, hide_index=True)


def detectar_quoting_csv_original(
    contenido_original: bytes, separador: str, encoding: str | None = None
) -> int:
    """Conserva el estilo de comillas global cuando el original cita todos los campos."""
    encoding_lectura = encoding or detectar_codificacion(contenido_original)
    primera_linea = contenido_original.decode(encoding_lectura).splitlines()[0]
    campos = next(csv.reader([primera_linea], delimiter=separador))
    campos_crudos = obtener_spans_campos_csv(primera_linea, separador)
    todos_entre_comillas = bool(campos) and all(
        primera_linea[inicio:fin].strip().startswith('"')
        and primera_linea[inicio:fin].strip().endswith('"')
        for inicio, fin in campos_crudos
    )
    return csv.QUOTE_ALL if todos_entre_comillas else csv.QUOTE_MINIMAL


def generar_csv_descarga_precios(
    contenido_original: bytes,
    df_original: pd.DataFrame,
    df_calculado: pd.DataFrame,
    costos_originales: pd.Series,
    separador_original: str,
    encoding: str | None = None,
    indices_afectados: set | None = None,
) -> bytes:
    """Exporta el CSV original completo cambiando Precio y Costo afectados."""
    return generar_csv_descarga_preservando_original(
        contenido_original,
        df_original,
        df_calculado,
        costos_originales,
        separador_original,
        encoding,
        indices_afectados,
    )


def generar_csv_descarga(
    df_final: pd.DataFrame, separador: str, encoding: str | None = "utf-8"
) -> bytes:
    """Exporta con separador original, QUOTE_MINIMAL y sin BOM."""
    encoding_exportacion = normalizar_codificacion_exportacion(encoding)
    csv_texto = df_final.to_csv(
        index=False,
        sep=separador,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )

    return csv_texto.encode(encoding_exportacion)


def normalizar_marca_tipo_producto(marca) -> str:
    """Normaliza marcas para clasificar listas tolerando espacios y apóstrofes."""
    texto = "" if pd.isna(marca) else str(marca)
    texto = texto.upper().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texto).split())


def obtener_clave_marca_tipo_producto(marca) -> tuple[str, ...]:
    """Devuelve tokens ordenados para tolerar inversiones como LIFE EXTENSION."""
    return tuple(sorted(normalizar_marca_tipo_producto(marca).split()))


CLAVES_MARCAS_SUPLEMENTOS_LISTAS = {
    obtener_clave_marca_tipo_producto(marca) for marca in MARCAS_SUPLEMENTOS_LISTAS
}


def clasificar_tipo_producto_listas(marca) -> str:
    """Clasifica productos de listas como Suplementos o Alimentos según su marca."""
    if obtener_clave_marca_tipo_producto(marca) in CLAVES_MARCAS_SUPLEMENTOS_LISTAS:
        return "Suplementos"
    return "Alimentos"


def calcular_mascara_tipo_producto_listas(
    df_listas: pd.DataFrame, tipo_producto: str | None
) -> pd.Series:
    """Calcula la máscara del filtro primario de tipo para listas de precios."""
    tipo_normalizado = (
        tipo_producto if tipo_producto in TIPOS_PRODUCTO_LISTAS else "Todos"
    )
    if tipo_normalizado == "Todos":
        return pd.Series(True, index=df_listas.index)

    tipos = df_listas["Marca"].map(clasificar_tipo_producto_listas)
    return tipos.eq(tipo_normalizado)


def filtrar_lista_por_tipo_producto(
    df_listas: pd.DataFrame, tipo_producto: str | None
) -> pd.DataFrame:
    """Filtra listas por Todos, Alimentos o Suplementos sin modificar cálculos."""
    mascara = calcular_mascara_tipo_producto_listas(df_listas, tipo_producto)
    return df_listas[mascara]


def obtener_metricas_tipo_producto_listas(
    df_listas: pd.DataFrame, tipo_producto: str | None
) -> dict[str, int]:
    """Cuenta productos totales, alimentos, suplementos y visibles por filtro."""
    tipos = df_listas["Marca"].map(clasificar_tipo_producto_listas)
    tipo_normalizado = (
        tipo_producto if tipo_producto in TIPOS_PRODUCTO_LISTAS else "Todos"
    )
    return {
        "Todos": int(len(df_listas)),
        "Alimentos": int(tipos.eq("Alimentos").sum()),
        "Suplementos": int(tipos.eq("Suplementos").sum()),
        "filtrados": int(
            calcular_mascara_tipo_producto_listas(df_listas, tipo_normalizado).sum()
        ),
    }


def preparar_tabla_listas_precios(df_original: pd.DataFrame) -> pd.DataFrame:
    """Crea una copia independiente para listas de precios sin tocar la simulación."""
    df_listas = df_original[["Nombre", "Marca", "SKU", "Costo"]].copy()
    df_listas["Costo"] = pd.to_numeric(
        df_listas["Costo"].map(normalizar_numero), errors="coerce"
    )
    return df_listas


def calcular_listas_precios(
    df_listas: pd.DataFrame,
    multiplicador_minorista: float,
    multiplicador_mayorista: float,
    multiplicadores_por_marca: dict[str, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Calcula precios minoristas y mayoristas usando overrides opcionales por marca."""
    df_calculado = df_listas.copy()
    multiplicadores_por_marca = multiplicadores_por_marca or {}
    df_calculado["Costo"] = pd.to_numeric(
        df_calculado["Costo"].map(normalizar_numero), errors="coerce"
    )
    df_calculado["Multiplicador Minorista"] = float(multiplicador_minorista)
    df_calculado["Multiplicador Mayorista"] = float(multiplicador_mayorista)

    for marca, multiplicadores in multiplicadores_por_marca.items():
        mascara_marca = df_calculado["Marca"].astype(str) == str(marca)
        if "minorista" in multiplicadores:
            df_calculado.loc[mascara_marca, "Multiplicador Minorista"] = float(
                multiplicadores["minorista"]
            )
        if "mayorista" in multiplicadores:
            df_calculado.loc[mascara_marca, "Multiplicador Mayorista"] = float(
                multiplicadores["mayorista"]
            )

    mascara_costo = tiene_costo_valido(df_calculado["Costo"])
    df_calculado["Precio Minorista"] = pd.NA
    df_calculado["Precio Mayorista"] = pd.NA
    df_calculado.loc[mascara_costo, "Precio Minorista"] = (
        df_calculado.loc[mascara_costo, "Costo"]
        * df_calculado.loc[mascara_costo, "Multiplicador Minorista"]
    )
    df_calculado.loc[mascara_costo, "Precio Mayorista"] = (
        df_calculado.loc[mascara_costo, "Costo"]
        * df_calculado.loc[mascara_costo, "Multiplicador Mayorista"]
    )

    return df_calculado


def normalizar_marcas_seleccionadas_listas(
    marcas: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[str]:
    """Normaliza el filtro mult marca de listas; vacío equivale a todas."""
    if marcas is None:
        return []
    if isinstance(marcas, str):
        marcas = [] if marcas == "Todas las marcas" else [marcas]
    return [str(marca) for marca in marcas if str(marca).strip()]


def filtrar_lista_para_pdf(
    df_listas_calculado: pd.DataFrame,
    marca: str | list[str] | tuple[str, ...] | set[str] | None,
    indices_incluidos: set | None = None,
    tipo_producto: str | None = "Todos",
) -> pd.DataFrame:
    """Filtra por tipo, marcas, exclusiones opcionales y productos sin costo válido."""
    df_pdf = filtrar_lista_por_tipo_producto(df_listas_calculado, tipo_producto)
    marcas = normalizar_marcas_seleccionadas_listas(marca)
    if marcas:
        df_pdf = df_pdf[df_pdf["Marca"].astype(str).isin(marcas)]
    if indices_incluidos is not None:
        df_pdf = df_pdf[df_pdf.index.isin(indices_incluidos)]
    return df_pdf[tiene_costo_valido(df_pdf["Costo"])]


def preparar_tabla_exclusion_pdf(
    df_listas_calculado: pd.DataFrame,
    inclusiones_pdf: dict,
    tipo_producto: str | None = "Todos",
) -> pd.DataFrame:
    """Arma la tabla editable de inclusión sin modificar la tabla de listas."""
    columnas = ["Nombre", "SKU", "Marca"]
    df_filtrado = filtrar_lista_por_tipo_producto(df_listas_calculado, tipo_producto)
    df_validos = df_filtrado[tiene_costo_valido(df_filtrado["Costo"])]
    tabla_exclusion = df_validos[columnas].copy()
    tabla_exclusion["Incluir en PDF"] = [
        bool(inclusiones_pdf.get(indice, True)) for indice in tabla_exclusion.index
    ]
    return tabla_exclusion


def filtrar_tabla_exclusion_pdf(
    tabla_exclusion: pd.DataFrame, nombre: str = "", sku: str = "", marca: str = ""
) -> pd.DataFrame:
    """Filtra la tabla de exclusión por Nombre, SKU y Marca."""
    tabla_filtrada = tabla_exclusion.copy()
    filtros = {"Nombre": nombre, "SKU": sku, "Marca": marca}
    for columna, texto in filtros.items():
        texto = str(texto).strip()
        if texto:
            coincide_filtro = (
                tabla_filtrada[columna]
                .astype(str)
                .str.contains(texto, case=False, na=False)
            )
            tabla_filtrada = tabla_filtrada[coincide_filtro]
    return tabla_filtrada


def formatear_moneda_pdf(valor) -> str:
    """Formatea precios para mostrar en los PDFs."""
    if pd.isna(valor):
        return ""
    return f"$ {float(valor):,.2f}"


def generar_pdf_lista_precios(
    df_listas_calculado: pd.DataFrame,
    tipo_lista: str,
    pie_pdf: str,
    marca: str | list[str] | tuple[str, ...] | set[str] | None = None,
    logo_path: Path | str = LOGO_KIKI_PREDETERMINADO,
    fecha_generacion: date | None = None,
    indices_incluidos: set | None = None,
    tipo_producto: str | None = "Todos",
) -> bytes:
    """Genera un PDF de lista de precios minorista o mayorista."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    tipo_normalizado = tipo_lista.strip().capitalize()
    if tipo_normalizado not in {"Minorista", "Mayorista"}:
        raise ValueError("tipo_lista debe ser Minorista o Mayorista")

    columna_precio = f"Precio {tipo_normalizado}"
    df_pdf = filtrar_lista_para_pdf(
        df_listas_calculado, marca, indices_incluidos, tipo_producto
    )
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    estilos = getSampleStyleSheet()
    estilo_celda = ParagraphStyle(
        "CeldaListaPrecios",
        parent=estilos["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        wordWrap="CJK",
        splitLongWords=True,
        spaceAfter=0,
    )
    estilo_celda_derecha = ParagraphStyle(
        "CeldaListaPreciosDerecha",
        parent=estilo_celda,
        alignment=2,
    )
    estilo_encabezado_tabla = ParagraphStyle(
        "EncabezadoListaPrecios",
        parent=estilo_celda,
        fontName="Helvetica-Bold",
    )
    elementos = []
    logo_path = Path(logo_path)
    if logo_path.exists():
        elementos.append(
            Image(str(logo_path), width=3.2 * cm, height=3.2 * cm, kind="proportional")
        )
        elementos.append(Spacer(1, 0.2 * cm))
    fecha = fecha_generacion or date.today()
    elementos.extend(
        [
            Paragraph("Lista de precios Kiki Market", estilos["Title"]),
            Paragraph(f"Tipo de lista: {tipo_normalizado}", estilos["Heading2"]),
            Paragraph(
                f"Tipo de producto: {tipo_producto or 'Todos'}", estilos["Normal"]
            ),
            Paragraph(
                f"Fecha de generación: {fecha.strftime('%d/%m/%Y')}", estilos["Normal"]
            ),
            Spacer(1, 0.4 * cm),
        ]
    )
    estilo_marca = ParagraphStyle(
        "MarcaListaPrecios",
        parent=estilos["Heading3"],
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#4A148C"),
        spaceBefore=8,
        spaceAfter=4,
    )
    for marca_grupo, df_marca in df_pdf.groupby(
        df_pdf["Marca"].astype(str), sort=True
    ):
        elementos.append(Paragraph(marca_grupo or "Sin marca", estilo_marca))
        datos = [
            [
                Paragraph("Nombre", estilo_encabezado_tabla),
                Paragraph("SKU", estilo_encabezado_tabla),
                Paragraph(columna_precio, estilo_encabezado_tabla),
            ]
        ]
        for _, fila in df_marca.iterrows():
            datos.append(
                [
                    Paragraph(str(fila.get("Nombre", "")), estilo_celda),
                    Paragraph(str(fila.get("SKU", "")), estilo_celda),
                    Paragraph(
                        formatear_moneda_pdf(fila.get(columna_precio)),
                        estilo_celda_derecha,
                    ),
                ]
            )
        tabla = Table(
            datos, repeatRows=1, colWidths=[11.0 * cm, 3.2 * cm, 3.3 * cm]
        )
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE7F6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elementos.append(tabla)
        elementos.append(Spacer(1, 0.25 * cm))
    elementos.extend([Spacer(1, 0.5 * cm), Paragraph(pie_pdf, estilos["Normal"])])
    documento.build(elementos)
    return buffer.getvalue()


def obtener_marcas_listas(
    df: pd.DataFrame, tipo_producto: str | None = "Todos"
) -> list[str]:
    """Devuelve marcas no vacías ordenadas respetando el tipo de producto."""
    df_filtrado = filtrar_lista_por_tipo_producto(df, tipo_producto)
    return sorted(
        marca
        for marca in df_filtrado["Marca"].dropna().astype(str).unique()
        if marca.strip()
    )


def mostrar_listas_precios(df: pd.DataFrame) -> None:
    """Muestra la funcionalidad independiente de listas sin tocar el simulador."""
    st.divider()
    with st.expander("Listas de precios", expanded=False):
        st.header("Listas de precios")
        st.write(
            "Generá listas Minorista y Mayorista desde una copia independiente del CSV "
            "cargado. Estos cambios no afectan la simulación ni la exportación CSV."
        )

        if "listas_tabla" not in st.session_state or st.session_state.get(
            "listas_archivo_id"
        ) != st.session_state.get("archivo_id"):
            st.session_state["listas_tabla"] = preparar_tabla_listas_precios(df)
            st.session_state["listas_multiplicadores_por_marca"] = {}
            st.session_state["listas_pdf_minorista"] = None
            st.session_state["listas_pdf_mayorista"] = None
            st.session_state["listas_firma_pdf"] = None
            st.session_state["listas_inclusiones_pdf"] = {}
            st.session_state["listas_archivo_id"] = st.session_state.get("archivo_id")

        col_min, col_may = st.columns(2)
        multiplicador_minorista = col_min.number_input(
            "Multiplicador Minorista",
            min_value=0.0,
            value=2.0,
            step=0.1,
            format="%.4f",
            key="listas_multiplicador_minorista_general",
        )
        multiplicador_mayorista = col_may.number_input(
            "Multiplicador Mayorista",
            min_value=0.0,
            value=1.6,
            step=0.1,
            format="%.4f",
            key="listas_multiplicador_mayorista_general",
        )

        marcas = obtener_marcas_listas(df)
        st.subheader("Multiplicadores por marca")
        if marcas:
            with st.form("listas_form_multiplicador_marca"):
                col_marca, col_minorista, col_mayorista = st.columns([2, 1, 1])
                marca_seleccionada = col_marca.selectbox(
                    "Marca",
                    options=marcas,
                    key="listas_marca_multiplicador",
                )
                productos_marca = int(
                    (
                        st.session_state["listas_tabla"]["Marca"].astype(str)
                        == str(marca_seleccionada)
                    ).sum()
                )
                valores_actuales = st.session_state[
                    "listas_multiplicadores_por_marca"
                ].get(marca_seleccionada, {})
                multiplicador_minorista_marca = col_minorista.number_input(
                    "Multiplicador Minorista por marca",
                    min_value=0.0,
                    value=float(
                        valores_actuales.get("minorista", multiplicador_minorista)
                    ),
                    step=0.1,
                    format="%.4f",
                    key="listas_multiplicador_minorista_marca",
                )
                multiplicador_mayorista_marca = col_mayorista.number_input(
                    "Multiplicador Mayorista por marca",
                    min_value=0.0,
                    value=float(
                        valores_actuales.get("mayorista", multiplicador_mayorista)
                    ),
                    step=0.1,
                    format="%.4f",
                    key="listas_multiplicador_mayorista_marca",
                )
                st.caption(
                    f"Productos afectados por {marca_seleccionada}: {productos_marca}"
                )
                aplicar_marca = st.form_submit_button(
                    "Aplicar multiplicadores a la marca"
                )

            if aplicar_marca:
                st.session_state["listas_multiplicadores_por_marca"][
                    marca_seleccionada
                ] = {
                    "minorista": multiplicador_minorista_marca,
                    "mayorista": multiplicador_mayorista_marca,
                }
                st.session_state["listas_pdf_minorista"] = None
                st.session_state["listas_pdf_mayorista"] = None
                st.success(
                    f"Multiplicadores aplicados a {productos_marca} productos de "
                    f"{marca_seleccionada}."
                )
        else:
            st.info("No hay marcas disponibles en el CSV.")

        st.subheader("Edición de costos para listas")
        st.caption(
            "Esta edición usa una copia separada y no modifica la exportación CSV del "
            "simulador."
        )
        tabla_listas_editada = st.data_editor(
            st.session_state["listas_tabla"],
            key="listas_editor_costos",
            use_container_width=True,
            num_rows="fixed",
            disabled=["Nombre", "Marca", "SKU"],
            column_config={
                "Costo": st.column_config.NumberColumn(
                    "Costo", min_value=0.0, format="%.2f"
                )
            },
        )
        if not tabla_listas_editada.equals(st.session_state["listas_tabla"]):
            st.session_state["listas_pdf_minorista"] = None
            st.session_state["listas_pdf_mayorista"] = None
        st.session_state["listas_tabla"] = tabla_listas_editada.copy()

        df_listas_calculado = calcular_listas_precios(
            tabla_listas_editada,
            multiplicador_minorista,
            multiplicador_mayorista,
            st.session_state["listas_multiplicadores_por_marca"],
        )
        tipo_producto_pdf = st.selectbox(
            "Tipo de producto",
            options=TIPOS_PRODUCTO_LISTAS,
            index=0,
            key="listas_tipo_producto",
        )
        metricas_tipo_producto = obtener_metricas_tipo_producto_listas(
            df_listas_calculado, tipo_producto_pdf
        )
        st.caption(
            "Productos en "
            f"{tipo_producto_pdf}: {metricas_tipo_producto['filtrados']} "
            f"(Todos: {metricas_tipo_producto['Todos']} | "
            f"Alimentos: {metricas_tipo_producto['Alimentos']} | "
            f"Suplementos: {metricas_tipo_producto['Suplementos']})"
        )
        df_listas_filtrado_tipo = filtrar_lista_por_tipo_producto(
            df_listas_calculado, tipo_producto_pdf
        )
        productos_sin_costo = int(
            (~tiene_costo_valido(df_listas_filtrado_tipo["Costo"])).sum()
        )
        if productos_sin_costo:
            st.warning(
                f"{productos_sin_costo} productos no tienen costo y no serán incluidos "
                "en el PDF"
            )

        st.subheader("Excluir productos del PDF")
        st.caption(
            "Desmarcá productos específicos para quitarlos solo de los PDFs. "
            "No modifica la simulación, los cálculos ni la exportación CSV."
        )
        tabla_exclusion_pdf = preparar_tabla_exclusion_pdf(
            df_listas_calculado,
            st.session_state["listas_inclusiones_pdf"],
            tipo_producto_pdf,
        )
        col_filtro_nombre, col_filtro_sku, col_filtro_marca = st.columns(3)
        filtro_exclusion_nombre = col_filtro_nombre.text_input(
            "Filtrar por Nombre", key="listas_filtro_exclusion_nombre"
        )
        filtro_exclusion_sku = col_filtro_sku.text_input(
            "Filtrar por SKU", key="listas_filtro_exclusion_sku"
        )
        filtro_exclusion_marca = col_filtro_marca.text_input(
            "Filtrar por Marca", key="listas_filtro_exclusion_marca"
        )
        tabla_exclusion_filtrada = filtrar_tabla_exclusion_pdf(
            tabla_exclusion_pdf,
            filtro_exclusion_nombre,
            filtro_exclusion_sku,
            filtro_exclusion_marca,
        )
        tabla_exclusion_editada = st.data_editor(
            tabla_exclusion_filtrada,
            key="listas_editor_exclusion_pdf",
            use_container_width=True,
            num_rows="fixed",
            disabled=["Nombre", "SKU", "Marca"],
            column_config={
                "Incluir en PDF": st.column_config.CheckboxColumn(
                    "Incluir en PDF", default=True
                )
            },
        )
        for indice, incluir in tabla_exclusion_editada["Incluir en PDF"].items():
            st.session_state["listas_inclusiones_pdf"][indice] = bool(incluir)
        indices_incluidos_pdf = set(
            preparar_tabla_exclusion_pdf(
                df_listas_calculado,
                st.session_state["listas_inclusiones_pdf"],
                tipo_producto_pdf,
            )
            .query("`Incluir en PDF` == True")
            .index
        )
        productos_excluidos_pdf = len(tabla_exclusion_pdf) - len(indices_incluidos_pdf)
        if productos_excluidos_pdf:
            st.info(f"Productos excluidos del PDF: {productos_excluidos_pdf}")

        st.subheader("Vista previa interna")
        st.dataframe(
            df_listas_filtrado_tipo[COLUMNAS_LISTA_PRECIOS],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Costo": st.column_config.NumberColumn("Costo", format="%.2f"),
                "Precio Minorista": st.column_config.NumberColumn(
                    "Precio Minorista", format="%.2f"
                ),
                "Precio Mayorista": st.column_config.NumberColumn(
                    "Precio Mayorista", format="%.2f"
                ),
            },
        )

        st.subheader("Generación de PDF")
        marcas_disponibles_pdf = obtener_marcas_listas(
            df_listas_calculado, tipo_producto_pdf
        )
        marcas_pdf = st.multiselect(
            "Marcas a incluir en el PDF",
            options=marcas_disponibles_pdf,
            key="listas_filtro_marcas_pdf",
            help="Dejá vacío para incluir todas las marcas del tipo de producto elegido.",
        )
        pie_pdf = st.text_area(
            "Pie del PDF",
            value=PIE_PDF_LISTA_PRECIOS,
            key="listas_pie_pdf",
            height=100,
        )
        marca_pdf = marcas_pdf
        df_pdf_filtrado = filtrar_lista_para_pdf(
            df_listas_calculado,
            marca_pdf,
            indices_incluidos_pdf,
            tipo_producto_pdf,
        )
        firma_pdf = (
            float(multiplicador_minorista),
            float(multiplicador_mayorista),
            tuple(
                sorted(
                    (
                        marca,
                        valores.get("minorista"),
                        valores.get("mayorista"),
                    )
                    for marca, valores in st.session_state[
                        "listas_multiplicadores_por_marca"
                    ].items()
                )
            ),
            tuple(sorted(marcas_pdf)),
            tipo_producto_pdf,
            pie_pdf,
            int(pd.util.hash_pandas_object(tabla_listas_editada, index=True).sum()),
            tuple(sorted(indices_incluidos_pdf)),
        )
        if st.session_state.get("listas_firma_pdf") != firma_pdf:
            st.session_state["listas_pdf_minorista"] = None
            st.session_state["listas_pdf_mayorista"] = None
            st.session_state["listas_firma_pdf"] = firma_pdf
        if df_pdf_filtrado.empty:
            st.warning(
                "No hay productos con costo válido para generar el PDF seleccionado."
            )

        col_pdf_minorista, col_pdf_mayorista = st.columns(2)
        with col_pdf_minorista:
            if st.button(
                "Generar PDF Minorista",
                key="listas_generar_pdf_minorista",
                use_container_width=True,
                disabled=df_pdf_filtrado.empty,
            ):
                try:
                    st.session_state["listas_pdf_minorista"] = (
                        generar_pdf_lista_precios(
                            df_listas_calculado,
                            "Minorista",
                            pie_pdf,
                            marca_pdf,
                            indices_incluidos=indices_incluidos_pdf,
                            tipo_producto=tipo_producto_pdf,
                        )
                    )
                except ModuleNotFoundError:
                    st.error(
                        "No se pudo generar el PDF porque falta instalar reportlab. "
                        "Revisá requirements.txt y reinstalá dependencias."
                    )
            if st.session_state.get("listas_pdf_minorista"):
                st.download_button(
                    "Descargar PDF Minorista",
                    data=st.session_state["listas_pdf_minorista"],
                    file_name="lista_precios_kiki_minorista.pdf",
                    mime="application/pdf",
                    key="listas_descargar_pdf_minorista",
                    use_container_width=True,
                )

        with col_pdf_mayorista:
            if st.button(
                "Generar PDF Mayorista",
                key="listas_generar_pdf_mayorista",
                use_container_width=True,
                disabled=df_pdf_filtrado.empty,
            ):
                try:
                    st.session_state["listas_pdf_mayorista"] = (
                        generar_pdf_lista_precios(
                            df_listas_calculado,
                            "Mayorista",
                            pie_pdf,
                            marca_pdf,
                            indices_incluidos=indices_incluidos_pdf,
                            tipo_producto=tipo_producto_pdf,
                        )
                    )
                except ModuleNotFoundError:
                    st.error(
                        "No se pudo generar el PDF porque falta instalar reportlab. "
                        "Revisá requirements.txt y reinstalá dependencias."
                    )
            if st.session_state.get("listas_pdf_mayorista"):
                st.download_button(
                    "Descargar PDF Mayorista",
                    data=st.session_state["listas_pdf_mayorista"],
                    file_name="lista_precios_kiki_mayorista.pdf",
                    mime="application/pdf",
                    key="listas_descargar_pdf_mayorista",
                    use_container_width=True,
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
        "Estado": st.column_config.TextColumn("Estado"),
        "Diferencia $": st.column_config.NumberColumn("Diferencia $", format="%.2f"),
        "Diferencia %": st.column_config.NumberColumn("Diferencia %", format="%.2f%%"),
    }


def mostrar_tabla_revision(df_vista: pd.DataFrame, config_columnas: dict) -> None:
    """Muestra una tabla de revisión con referencia visual por estado."""
    st.caption(REFERENCIA_ESTADOS)
    st.dataframe(
        df_vista,
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
    mascara_modificado = pd.Series(True, index=[ultimo_indice])
    st.session_state["ultimo_producto_modificado"] = preparar_vista_con_diferencias(
        df_calculado.loc[[ultimo_indice]], mascara_modificado
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
    codificacion = detectar_codificacion(contenido)

    try:
        df = leer_csv(contenido, separador, codificacion)
    except Exception as error:
        st.error(
            f"No se pudo leer el CSV. Revisá el archivo e intentá nuevamente. Detalle: {error}"
        )
        st.stop()

    st.success("CSV cargado correctamente")
    filas_csv, productos_unicos, variantes_repetidas = obtener_metricas_csv(df)
    columnas_metricas = st.columns(3)
    columnas_metricas[0].metric("Filas del CSV", filas_csv)
    if productos_unicos is None:
        columnas_metricas[1].metric("Productos únicos", "-")
        columnas_metricas[2].metric("Variantes/filas repetidas", "-")
        st.warning(
            f"No se encontró la columna {COLUMNA_IDENTIFICADOR_URL!r} para contar productos únicos."
        )
    else:
        columnas_metricas[1].metric("Productos únicos", productos_unicos)
        columnas_metricas[2].metric("Variantes/filas repetidas", variantes_repetidas)
    st.caption(
        "El CSV puede tener más filas que productos porque Tienda Nube usa una fila por variante."
    )
    mostrar_productos_con_variantes(df)
    st.write(f"Columnas: **{df.shape[1]}**")
    st.write(f"Separador detectado: **{repr(separador)}**")
    st.write(
        "Codificación detectada para exportar sin BOM: "
        f"**{normalizar_codificacion_exportacion(codificacion)}**"
    )

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
    st.caption("Ejemplo: 2 = costo x 2")
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
            "Aplicar a todos los productos"
        )

    if aplicar_global:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        indices_afectados_accion = tabla_actual.index.tolist()
        tabla_actual.loc[indices_afectados_accion, "Multiplicador"] = (
            multiplicador_global
        )
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_afectados_accion)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_afectados_accion)
        st.success(
            construir_mensaje_aplicacion(
                f"Multiplicador {multiplicador_global}",
                tabla_actual,
                indices_afectados_accion,
                "del CSV",
            )
        )

    st.subheader("Margen objetivo")
    st.caption("Ejemplo: 30% = costo x 1.30")
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
            "Aplicar margen objetivo a todos los productos"
        )

    if aplicar_margen_objetivo:
        tabla_actual = st.session_state["tabla_trabajo"].copy()
        indices_afectados_accion = tabla_actual.index.tolist()
        multiplicador_margen = 1 + margen_objetivo / 100
        tabla_actual.loc[indices_afectados_accion, "Multiplicador"] = (
            multiplicador_margen
        )
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_afectados_accion)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_afectados_accion)
        st.success(
            construir_mensaje_aplicacion(
                f"Margen objetivo {margen_objetivo}%",
                tabla_actual,
                indices_afectados_accion,
                "del CSV",
            )
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
    st.caption("Aplicá un multiplicador a todos los productos de una marca.")
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
        indices_afectados_accion = tabla_actual.index[mascara_marca].tolist()
        tabla_actual.loc[mascara_marca, "Multiplicador"] = multiplicador_masivo
        tabla_actual = recalcular_precios(tabla_actual)
        st.session_state["tabla_trabajo"] = tabla_actual
        st.session_state["indices_afectados"].update(indices_afectados_accion)
        st.session_state["editor_version"] += 1
        actualizar_ultimo_producto(tabla_actual, indices_afectados_accion)
        st.success(
            construir_mensaje_aplicacion(
                f"Multiplicador {multiplicador_masivo}",
                tabla_actual,
                indices_afectados_accion,
                "de la marca",
            )
        )

    st.subheader("Multiplicador por producto")
    st.caption("Aplicá un multiplicador solo a un producto específico.")
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
            construir_mensaje_aplicacion(
                f"Multiplicador {multiplicador_producto}",
                tabla_actual,
                [producto_seleccionado],
                f"del producto: {producto_aplicado}",
            )
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
    mascara_modificados = calcular_mascara_modificados(
        df_calculado, costos_originales, indices_afectados
    )
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
    if busqueda_simulacion.strip():
        productos_filtrados_simulacion = filtrar_productos(
            df_calculado, busqueda_simulacion
        )
        productos_encontrados = preparar_vista_con_diferencias(
            productos_filtrados_simulacion, mascara_modificados
        )[COLUMNAS_BUSQUEDA_SIMULACION]
        st.caption(f"Coincidencias: {len(productos_encontrados)}")
        mostrar_tabla_revision(productos_encontrados, config_columnas)
    else:
        st.info("Buscá por nombre, SKU o marca para revisar productos específicos.")

    st.subheader("Vista previa de la simulación")
    st.caption(
        "Vista previa limitada para revisión rápida. El CSV final se exporta completo."
    )
    resultado_calculado = preparar_vista_con_diferencias(
        df_calculado, mascara_modificados
    )[COLUMNAS_RESULTADO_CALCULADO].head(LIMITE_VISTA_PREVIA)
    mostrar_tabla_revision(resultado_calculado, config_columnas)

    st.subheader("Exportar CSV final")
    st.info(
        "Al importar en Tienda Nube, no ignores estas columnas: Identificador de "
        "URL, Nombre, Nombre/Valor de propiedad 1, 2 y 3, Precio y Costo."
    )
    mostrar_advertencias_exportacion(df_calculado, mascara_modificados)

    precios_realmente_modificados = int(
        calcular_mascara_precios_exportados(
            df_calculado, costos_originales, indices_afectados
        ).sum()
    )
    metricas_exportacion = st.columns(2)
    metricas_exportacion[0].metric("Filas que serán exportadas", len(df))
    metricas_exportacion[1].metric(
        "Precios realmente modificados", precios_realmente_modificados
    )

    csv_precios_actualizados = generar_csv_descarga_precios(
        contenido,
        df,
        df_calculado,
        costos_originales,
        separador,
        codificacion,
        indices_afectados,
    )
    columnas_descarga = st.columns(2)
    with columnas_descarga[0]:
        st.download_button(
            label="Descargar CSV completo para Tienda Nube",
            data=csv_precios_actualizados,
            file_name="tienda_nube_precios_actualizados.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with columnas_descarga[1]:
        st.download_button(
            label="Descargar CSV solo actualización de precios",
            data=csv_precios_actualizados,
            file_name="tienda_nube_solo_actualizacion_precios.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )
        st.caption(
            "Conserva exactamente las columnas, el orden y las filas del CSV original; "
            "solo cambia Precio y Costo en las filas afectadas."
        )

    mostrar_listas_precios(df)


if __name__ == "__main__":
    main()
