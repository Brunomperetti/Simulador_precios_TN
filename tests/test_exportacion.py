import csv
import unittest
from io import StringIO

import pandas as pd

from app import (
    calcular_mascara_precios_actualizados,
    calcular_resumen_aplicacion,
    construir_dataframe_exportacion,
    construir_mensaje_aplicacion,
    detectar_codificacion,
    generar_csv_descarga,
    obtener_metricas_csv,
    obtener_productos_con_variantes,
    preparar_tabla_trabajo,
    recalcular_precios,
)


class ExportacionTiendaNubeTest(unittest.TestCase):
    def crear_csv_original(self):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
        ] + [f"Columna {numero}" for numero in range(7, 31)]
        filas = [
            ["producto-a", "Producto A", "Marca 1", "SKU-A", "16,850.00", ""],
            [
                "producto-b",
                "Producto B",
                "Marca 2",
                "SKU-B",
                "10,000.00",
                "8,762.64",
            ],
            [
                "producto-b",
                "Producto B talle M",
                "Marca 2",
                "SKU-B-M",
                "10,000.00",
                "8,762.64",
            ],
            [
                "producto-c",
                "Producto C",
                "Marca 3",
                "SKU-C",
                "20,000.00",
                "5,000.00",
            ],
        ]
        return pd.DataFrame(
            [
                fila + [f"valor-{indice}-{columna}" for columna in range(7, 31)]
                for indice, fila in enumerate(filas)
            ],
            columns=columnas,
        )

    def test_producto_con_multiplicador_uno_no_afectado_conserva_precio_original(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )

        self.assertEqual(df_exportado.loc[1, "Precio"], df_original.loc[1, "Precio"])
        self.assertEqual(df_exportado.loc[2, "Precio"], df_original.loc[2, "Precio"])
        self.assertEqual(df_exportado.loc[3, "Precio"], df_original.loc[3, "Precio"])

    def test_producto_con_multiplicador_distinto_exporta_costo_por_multiplicador(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 2.5

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )

        self.assertEqual(df_exportado.loc[1, "Precio"], "21906.60")
        self.assertEqual(df_exportado.loc[2, "Precio"], df_original.loc[2, "Precio"])

    def test_csv_exportado_precio_usa_float_y_sin_separador_de_miles(self):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
        ]
        df_original = pd.DataFrame(
            [
                [
                    "rompepiedras-colabella",
                    "Rompepiedras Colabella",
                    "Colabella",
                    "ROMPE",
                    "0.00",
                    "8762.64",
                ],
                [
                    "clara-huevo-colabella",
                    "Clara de Huevo Colabella",
                    "Colabella",
                    "CLARA",
                    "0.00",
                    "27667.76",
                ],
            ],
            columns=columnas,
        )
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo["Multiplicador"] = 2.4

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )
        csv_exportado = generar_csv_descarga(df_exportado, ";")
        df_releido = pd.read_csv(
            StringIO(csv_exportado.decode("utf-8-sig")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(float(df_calculado.loc[0, "Nuevo Precio"]), 8762.64 * 2.4)
        self.assertEqual(round(df_calculado.loc[0, "Nuevo Precio"], 2), 21030.34)
        self.assertEqual(round(df_calculado.loc[1, "Nuevo Precio"], 2), 66402.62)
        self.assertEqual(df_releido.loc[0, "Precio"], "21030.34")
        self.assertEqual(df_releido.loc[1, "Precio"], "66402.62")
        self.assertNotIn("21,030.34", csv_exportado.decode("utf-8-sig"))
        self.assertNotIn("21.030,34", csv_exportado.decode("utf-8-sig"))
        self.assertNotIn("21,030,336.00", csv_exportado.decode("utf-8-sig"))

    def test_producto_sin_costo_afectado_conserva_precio_original(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[0, "Multiplicador"] = 2.5

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales, {0}
        )

        self.assertEqual(df_exportado.loc[0, "Precio"], df_original.loc[0, "Precio"])

    def test_csv_exportado_no_modifica_precios_no_tocados(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 2.5

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )
        csv_exportado = generar_csv_descarga(df_exportado, ";")
        df_releido = pd.read_csv(
            StringIO(csv_exportado.decode("utf-8-sig")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(df_releido.loc[1, "Precio"], "21906.60")
        self.assertEqual(df_releido.loc[2, "Precio"], df_original.loc[2, "Precio"])
        self.assertEqual(df_releido.loc[3, "Precio"], df_original.loc[3, "Precio"])

    def test_producto_sin_costo_conserva_precio_original_al_exportar(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )

        self.assertEqual(df_exportado.loc[0, "Precio"], "16,850.00")
        self.assertEqual(df_exportado.loc[0, "Costo"], "")

    def test_csv_exportado_mantiene_filas_columnas_y_sin_auxiliares(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 2
        df_trabajo.loc[2, "Costo"] = 9000
        df_calculado = recalcular_precios(df_trabajo)

        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )
        csv_exportado = generar_csv_descarga(df_exportado, ";")
        df_releido = pd.read_csv(
            StringIO(csv_exportado.decode("utf-8-sig")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(df_releido.shape, df_original.shape)
        self.assertEqual(list(df_releido.columns), list(df_original.columns))
        self.assertNotIn("Nuevo Precio", df_releido.columns)
        self.assertNotIn("Multiplicador", df_releido.columns)
        self.assertEqual(df_releido.loc[1, "Precio"], "17525.28")
        self.assertEqual(df_releido.loc[1, "Costo"], "8,762.64")
        self.assertEqual(df_releido.loc[2, "Costo"], "9000.00")

    def test_csv_exportado_imita_formato_tienda_nube_sin_bom_y_con_quote_minimal(self):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
        ] + [f"Columna {numero}" for numero in range(7, 31)]
        filas = [
            [
                "producto-a",
                "Producto A; edición especial",
                "Marca Ñ",
                "SKU-A",
                "16,850.00",
                "8,762.64",
            ],
            ["producto-b", "Producto B", "Marca 2", "SKU-B", "10,000.00", "5,000.00"],
        ]
        df_original = pd.DataFrame(
            [
                fila + [f"valor-{indice}-{columna}" for columna in range(7, 31)]
                for indice, fila in enumerate(filas)
            ],
            columns=columnas,
        )
        csv_original = df_original.to_csv(
            index=False,
            sep=";",
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        ).encode("latin1")
        codificacion = detectar_codificacion(csv_original)
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 2.5

        df_calculado = recalcular_precios(df_trabajo)
        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )
        csv_exportado = generar_csv_descarga(df_exportado, ";", codificacion)
        texto_exportado = csv_exportado.decode("latin1")
        filas_exportadas = list(csv.reader(StringIO(texto_exportado), delimiter=";"))

        self.assertFalse(csv_exportado.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(codificacion, "latin1")
        self.assertEqual(texto_exportado.splitlines()[0].count(";"), len(columnas) - 1)
        self.assertEqual(len(filas_exportadas), len(filas) + 1)
        self.assertTrue(all(len(fila) == len(columnas) for fila in filas_exportadas))
        self.assertEqual(filas_exportadas[0], columnas)
        self.assertIn('"Producto A; edición especial"', texto_exportado)
        self.assertEqual(filas_exportadas[2][columnas.index("Precio")], "12500.00")
        self.assertEqual(filas_exportadas[1][columnas.index("Precio")], "16,850.00")

    def test_metricas_csv_cuenta_productos_unicos_y_variantes(self):
        filas, productos_unicos, variantes = obtener_metricas_csv(
            self.crear_csv_original()
        )

        self.assertEqual(filas, 4)
        self.assertEqual(productos_unicos, 3)
        self.assertEqual(variantes, 1)

    def test_identifica_variantes_por_identificador_url_repetido(self):
        columnas = [
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
        df_original = pd.DataFrame(
            [
                [
                    "producto-a",
                    "Producto A",
                    "Marca 1",
                    "SKU-A",
                    "Talle",
                    "S",
                    "Color",
                    "Rojo",
                    "",
                    "",
                    "100.00",
                    "50.00",
                ],
                [
                    "producto-a",
                    "Producto A",
                    "Marca 1",
                    "SKU-A-M",
                    "Talle",
                    "M",
                    "Color",
                    "Rojo",
                    "",
                    "",
                    "100.00",
                    "50.00",
                ],
                [
                    "producto-b",
                    "Producto B",
                    "Marca 2",
                    "SKU-B",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "200.00",
                    "100.00",
                ],
            ],
            columns=columnas,
        )

        variantes = obtener_productos_con_variantes(df_original)

        self.assertEqual(list(variantes.columns), columnas)
        self.assertEqual(variantes.shape, (2, 12))
        self.assertEqual(
            variantes["Identificador de URL"].tolist(), ["producto-a", "producto-a"]
        )
        self.assertEqual(variantes["SKU"].tolist(), ["SKU-A", "SKU-A-M"])

    def test_mensaje_marca_informa_afectados_actualizados_y_sin_costo(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        indices_marca = df_trabajo.index[df_trabajo["Marca"].eq("Marca 1")].tolist()
        df_trabajo.loc[indices_marca, "Multiplicador"] = 3.1
        df_calculado = recalcular_precios(df_trabajo)

        mensaje = construir_mensaje_aplicacion(
            "Multiplicador 3.1", df_calculado, indices_marca, "de la marca"
        )
        resumen = calcular_resumen_aplicacion(df_calculado, indices_marca)

        self.assertEqual(
            mensaje,
            "Multiplicador 3.1 aplicado a 1 productos de la marca. "
            "0 precios fueron actualizados. "
            "1 productos quedaron sin modificar por no tener costo válido.",
        )
        self.assertEqual(
            resumen,
            {"afectados": 1, "precios_actualizados": 0, "sin_costo_valido": 1},
        )

    def test_producto_sin_costo_afectado_no_figura_como_precio_actualizado(self):
        df_original = self.crear_csv_original()
        df_trabajo = preparar_tabla_trabajo(df_original)
        df_trabajo.loc[0, "Multiplicador"] = 3.1
        df_calculado = recalcular_precios(df_trabajo)

        precios_actualizados = calcular_mascara_precios_actualizados(df_calculado, {0})
        resumen = calcular_resumen_aplicacion(df_calculado, {0})

        self.assertFalse(bool(precios_actualizados.loc[0]))
        self.assertEqual(resumen["precios_actualizados"], 0)
        self.assertEqual(resumen["sin_costo_valido"], 1)

    def test_csv_exportado_mantiene_394_filas_y_30_columnas(self):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
        ] + [f"Columna {numero}" for numero in range(7, 31)]
        filas = []
        for indice in range(394):
            filas.append(
                [
                    f"producto-{indice}",
                    f"Producto {indice}",
                    "Marca 1" if indice % 2 == 0 else "Marca 2",
                    f"SKU-{indice}",
                    "100.00",
                    "50.00",
                ]
                + [f"valor-{indice}-{columna}" for columna in range(7, 31)]
            )
        df_original = pd.DataFrame(filas, columns=columnas)
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[0, "Multiplicador"] = 2.4
        df_calculado = recalcular_precios(df_trabajo)

        df_exportado = construir_dataframe_exportacion(
            df_original, df_calculado, costos_originales
        )
        csv_exportado = generar_csv_descarga(df_exportado, ";")
        df_releido = pd.read_csv(
            StringIO(csv_exportado.decode("utf-8")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(df_releido.shape, (394, 30))
        self.assertEqual(list(df_releido.columns), columnas)


if __name__ == "__main__":
    unittest.main()
