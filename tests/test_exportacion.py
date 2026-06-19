import csv
import importlib.util
import unittest
from io import StringIO

import pandas as pd

from app import (
    calcular_mascara_precios_actualizados,
    calcular_resumen_aplicacion,
    construir_dataframe_exportacion,
    construir_dataframe_exportacion_precios,
    construir_mensaje_aplicacion,
    detectar_codificacion,
    generar_csv_descarga,
    generar_csv_descarga_precios,
    generar_csv_descarga_preservando_original,
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

    def crear_csv_original_con_propiedades(self):
        return pd.DataFrame(
            [
                [
                    "remera",
                    "Remera clásica",
                    "Marca 1",
                    "REM-M",
                    "Talle",
                    "M",
                    "Color",
                    "Azul",
                    "",
                    "",
                    "10,000.00",
                    "5,000.00",
                    "dato auxiliar",
                ],
                [
                    "remera",
                    "Remera clásica",
                    "Marca 1",
                    "REM-L",
                    "Talle",
                    "L",
                    "Color",
                    "Rojo",
                    "",
                    "",
                    "10,000.00",
                    "5,000.00",
                    "otro dato",
                ],
                [
                    "gorra",
                    "Gorra",
                    "Marca 2",
                    "GOR-1",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "8,000.00",
                    "",
                    "sin costo",
                ],
            ],
            columns=[
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
                "Columna auxiliar",
            ],
        )

    def crear_caso_regresion_sku_273700(self, precio="10,346.00"):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
            "Stock",
            "Descripción",
        ]
        filas = [
            [
                "producto-sin-cambios",
                "Producto sin cambios",
                "Marca Ñ",
                "111111",
                "1,500.00",
                "750.00",
                "4",
                "Conservar; exactamente",
            ],
            [
                "producto-273700",
                "Producto representativo",
                "Marca Ñ",
                "273700",
                precio,
                "8,280.00",
                "7",
                "Texto, comas y Ñ intactos",
            ],
            [
                "producto-final",
                "Producto final",
                "Otra marca",
                "999999",
                "2,000.00",
                "1,000.00",
                "0",
                "Última fila intacta",
            ],
        ]
        contenido_original = StringIO()
        escritor = csv.writer(
            contenido_original,
            delimiter=";",
            quoting=csv.QUOTE_ALL,
            lineterminator="\r\n",
        )
        escritor.writerow(columnas)
        escritor.writerows(filas)
        contenido_original = contenido_original.getvalue().encode("latin1")
        df_original = pd.read_csv(
            StringIO(contenido_original.decode("latin1")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )
        return contenido_original, df_original

    def exportar_caso_regresion_sku_273700(
        self, *, precio="10,346.00", costo_editado=None, multiplicador=1
    ):
        contenido_original, df_original = self.crear_caso_regresion_sku_273700(precio)
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        if costo_editado is not None:
            df_trabajo.loc[1, "Costo"] = costo_editado
        df_trabajo.loc[1, "Multiplicador"] = multiplicador
        df_calculado = recalcular_precios(df_trabajo)
        contenido_exportado = generar_csv_descarga_preservando_original(
            contenido_original,
            df_original,
            df_calculado,
            costos_originales,
            ";",
            "latin1",
            {1},
        )
        df_exportado = pd.read_csv(
            StringIO(contenido_exportado.decode("latin1")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )
        return contenido_original, contenido_exportado, df_original, df_exportado

    def test_exportacion_sku_273700_modificando_solo_costo_exporta_nuevo_costo(self):
        _, _, _, df_exportado = self.exportar_caso_regresion_sku_273700(
            costo_editado=10346
        )

        self.assertEqual(df_exportado.loc[1, "SKU"], "273700")
        self.assertEqual(df_exportado.loc[1, "Costo"], "10,346.00")
        self.assertEqual(df_exportado.loc[1, "Precio"], "10,346.00")

    def test_exportacion_sku_273700_modificando_solo_precio_exporta_nuevo_precio(self):
        _, _, _, df_exportado = self.exportar_caso_regresion_sku_273700(
            precio="8,280.00", multiplicador=1.25
        )

        self.assertEqual(df_exportado.loc[1, "SKU"], "273700")
        self.assertEqual(df_exportado.loc[1, "Precio"], "10,350.00")
        self.assertEqual(df_exportado.loc[1, "Costo"], "8,280.00")

    def test_exportacion_sku_273700_modificando_precio_y_costo_exporta_ambos(self):
        _, _, _, df_exportado = self.exportar_caso_regresion_sku_273700(
            precio="8,280.00", costo_editado=10346
        )

        self.assertEqual(df_exportado.loc[1, "SKU"], "273700")
        self.assertEqual(df_exportado.loc[1, "Precio"], "10,346.00")
        self.assertEqual(df_exportado.loc[1, "Costo"], "10,346.00")

    def test_exportacion_preservada_mantiene_otras_columnas_y_filas_intactas(self):
        contenido_original, contenido_exportado, df_original, df_exportado = (
            self.exportar_caso_regresion_sku_273700(
                precio="8,280.00", costo_editado=10346
            )
        )
        lineas_originales = contenido_original.splitlines(keepends=True)
        lineas_exportadas = contenido_exportado.splitlines(keepends=True)
        columnas_intactas = [
            columna
            for columna in df_original.columns
            if columna not in {"Precio", "Costo"}
        ]

        self.assertEqual(
            df_exportado.loc[1, columnas_intactas].tolist(),
            df_original.loc[1, columnas_intactas].tolist(),
        )
        self.assertEqual(lineas_exportadas[0], lineas_originales[0])
        self.assertEqual(lineas_exportadas[1], lineas_originales[1])
        self.assertEqual(lineas_exportadas[3], lineas_originales[3])
        self.assertEqual(len(lineas_exportadas), len(lineas_originales))
        self.assertEqual(list(df_exportado.columns), list(df_original.columns))
        self.assertEqual(df_exportado.shape, df_original.shape)

    def test_exportacion_precios_preserva_csv_original_excepto_precios_modificados(
        self,
    ):
        df_base = self.crear_csv_original_con_propiedades()
        df_base.loc[1, "Nombre"] = ""
        contenido_original = df_base.to_csv(
            index=False,
            sep=";",
            quoting=csv.QUOTE_ALL,
            lineterminator="\r\n",
        ).encode("utf-8")
        df_original = pd.read_csv(
            StringIO(contenido_original.decode("utf-8")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 3
        df_calculado = recalcular_precios(df_trabajo)

        df_exportado = construir_dataframe_exportacion_precios(
            df_original, df_calculado, costos_originales, {1}
        )
        contenido_exportado = generar_csv_descarga_precios(
            contenido_original,
            df_original,
            df_calculado,
            costos_originales,
            ";",
            "utf-8",
            {1},
        )
        df_releido = pd.read_csv(
            StringIO(contenido_exportado.decode("utf-8")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(df_exportado.shape, df_original.shape)
        self.assertEqual(df_releido.shape, df_original.shape)
        self.assertEqual(list(df_exportado.columns), list(df_original.columns))
        self.assertEqual(list(df_releido.columns), list(df_original.columns))
        self.assertEqual(
            contenido_exportado.splitlines(keepends=True)[0],
            contenido_original.splitlines(keepends=True)[0],
        )

        columnas_no_precio = [
            columna for columna in df_original.columns if columna != "Precio"
        ]
        pd.testing.assert_frame_equal(
            df_exportado[columnas_no_precio],
            df_original[columnas_no_precio],
        )
        pd.testing.assert_frame_equal(
            df_releido[columnas_no_precio],
            df_original[columnas_no_precio],
        )
        self.assertEqual(df_releido.loc[1, "Precio"], "15,000.00")
        self.assertEqual(df_releido.loc[0, "Precio"], df_original.loc[0, "Precio"])
        self.assertEqual(df_releido.loc[2, "Precio"], df_original.loc[2, "Precio"])
        self.assertEqual(
            contenido_exportado.splitlines(keepends=True)[1],
            contenido_original.splitlines(keepends=True)[1],
        )
        self.assertEqual(
            contenido_exportado.splitlines(keepends=True)[3],
            contenido_original.splitlines(keepends=True)[3],
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

        self.assertEqual(df_exportado.loc[1, "Precio"], "21,906.60")
        self.assertEqual(df_exportado.loc[2, "Precio"], df_original.loc[2, "Precio"])

    def test_csv_exportado_precio_usa_float_y_formato_tienda_nube(self):
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
        self.assertEqual(df_releido.loc[0, "Precio"], "21,030.34")
        self.assertEqual(df_releido.loc[1, "Precio"], "66,402.62")
        self.assertIn("21,030.34", csv_exportado.decode("utf-8-sig"))
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

        self.assertEqual(df_releido.loc[1, "Precio"], "21,906.60")
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
        self.assertEqual(df_releido.loc[1, "Precio"], "17,525.28")
        self.assertEqual(df_releido.loc[1, "Costo"], "8,762.64")
        self.assertEqual(df_releido.loc[2, "Costo"], "9,000.00")

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
        self.assertEqual(filas_exportadas[2][columnas.index("Precio")], "12,500.00")
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

    def test_exportacion_preserva_original_y_cambia_solo_campos_modificados(self):
        columnas = [
            "Identificador de URL",
            "Nombre",
            "Marca",
            "SKU",
            "Precio",
            "Costo",
        ] + [f"Columna {numero}" for numero in range(7, 31)]
        encabezado = ";".join(f'"{columna}"' for columna in columnas) + "\r\n"
        lineas = [encabezado]
        for indice in range(394):
            precio = "10,000.00" if indice == 1 else "100.00"
            costo = "8,762.64" if indice == 1 else ("" if indice == 2 else "50.00")
            campos = [
                f"producto-{indice}",
                "Producto 0; edición Ñ" if indice == 0 else f"Producto {indice}",
                "Marca 1" if indice % 2 == 0 else "Marca 2",
                f"SKU-{indice}",
                precio,
                costo,
            ] + [f"valor-{indice}-{columna}" for columna in range(7, 31)]
            lineas.append(";".join(f'"{campo}"' for campo in campos) + "\r\n")
        csv_original = "".join(lineas).encode("latin1")
        df_original = pd.read_csv(
            StringIO(csv_original.decode("latin1")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )
        df_trabajo = preparar_tabla_trabajo(df_original)
        costos_originales = df_trabajo["Costo"].copy()
        df_trabajo.loc[1, "Multiplicador"] = 2
        df_trabajo.loc[2, "Multiplicador"] = 3
        df_calculado = recalcular_precios(df_trabajo)

        csv_exportado = generar_csv_descarga_preservando_original(
            csv_original,
            df_original,
            df_calculado,
            costos_originales,
            ";",
            "latin1",
            {1, 2},
        )
        lineas_exportadas = csv_exportado.splitlines(keepends=True)
        fila_original_modificada = next(csv.reader([lineas[1 + 1]], delimiter=";"))
        fila_exportada_modificada = next(
            csv.reader([lineas_exportadas[1 + 1].decode("latin1")], delimiter=";")
        )
        df_releido = pd.read_csv(
            StringIO(csv_exportado.decode("latin1")),
            sep=";",
            dtype=str,
            keep_default_na=False,
        )

        self.assertEqual(lineas_exportadas[0], lineas[0].encode("latin1"))
        self.assertEqual(lineas_exportadas[1], lineas[1].encode("latin1"))
        self.assertEqual(fila_exportada_modificada[4], "17,525.28")
        self.assertEqual(fila_exportada_modificada[:4], fila_original_modificada[:4])
        self.assertEqual(fila_exportada_modificada[5:], fila_original_modificada[5:])
        self.assertEqual(lineas_exportadas[3], lineas[3].encode("latin1"))
        self.assertEqual(df_releido.shape, (394, 30))
        self.assertEqual(list(df_releido.columns), columnas)
        self.assertNotIn("Nuevo Precio", df_releido.columns)
        self.assertNotIn("Multiplicador", df_releido.columns)
        self.assertIn(b'"17,525.28"', csv_exportado)


class ListasPreciosTest(unittest.TestCase):
    def crear_dataframe_listas(self):
        return pd.DataFrame(
            [
                ["Producto A", "Marca 1", "SKU-A", "1.000,50"],
                ["Producto B", "Marca 2", "SKU-B", "2000"],
                ["Producto C", "Marca 1", "SKU-C", ""],
            ],
            columns=["Nombre", "Marca", "SKU", "Costo"],
        )

    def test_listas_precios_usa_copia_y_multiplicadores_por_marca(self):
        from app import calcular_listas_precios, preparar_tabla_listas_precios

        df_original = self.crear_dataframe_listas()
        df_listas = preparar_tabla_listas_precios(df_original)
        df_listas.loc[0, "Costo"] = 1500

        df_calculado = calcular_listas_precios(
            df_listas,
            2.0,
            1.5,
            {"Marca 1": {"minorista": 3.0, "mayorista": 2.0}},
        )

        self.assertEqual(df_original.loc[0, "Costo"], "1.000,50")
        self.assertEqual(df_calculado.loc[0, "Precio Minorista"], 4500)
        self.assertEqual(df_calculado.loc[0, "Precio Mayorista"], 3000)
        self.assertEqual(df_calculado.loc[1, "Precio Minorista"], 4000)
        self.assertTrue(pd.isna(df_calculado.loc[2, "Precio Minorista"]))

    def test_productos_sin_costo_no_van_a_lista_pdf(self):
        from app import (
            calcular_listas_precios,
            filtrar_lista_para_pdf,
            preparar_tabla_listas_precios,
        )

        df_listas = preparar_tabla_listas_precios(self.crear_dataframe_listas())
        df_calculado = calcular_listas_precios(df_listas, 2.0, 1.5)
        df_pdf = filtrar_lista_para_pdf(df_calculado, "Marca 1")

        self.assertEqual(df_pdf["SKU"].tolist(), ["SKU-A"])
        self.assertNotIn("SKU-C", df_pdf["SKU"].tolist())

    def test_exclusiones_pdf_respetan_marca_y_no_alteran_calculos(self):
        from app import (
            calcular_listas_precios,
            filtrar_lista_para_pdf,
            preparar_tabla_exclusion_pdf,
            preparar_tabla_listas_precios,
        )

        df_listas = preparar_tabla_listas_precios(self.crear_dataframe_listas())
        df_calculado = calcular_listas_precios(df_listas, 2.0, 1.5)
        df_calculado_original = df_calculado.copy(deep=True)

        tabla_exclusion = preparar_tabla_exclusion_pdf(df_calculado, {})
        self.assertEqual(tabla_exclusion["Incluir en PDF"].tolist(), [True, True])

        df_sin_exclusiones = filtrar_lista_para_pdf(df_calculado, None)
        df_con_exclusiones = filtrar_lista_para_pdf(df_calculado, None, {0})
        df_marca_excluida = filtrar_lista_para_pdf(df_calculado, "Marca 2", {0})

        self.assertEqual(df_sin_exclusiones["SKU"].tolist(), ["SKU-A", "SKU-B"])
        self.assertEqual(df_con_exclusiones["SKU"].tolist(), ["SKU-A"])
        self.assertTrue(df_marca_excluida.empty)
        pd.testing.assert_frame_equal(df_calculado, df_calculado_original)

    def test_tabla_exclusion_pdf_filtra_por_nombre_sku_y_marca(self):
        from app import (
            calcular_listas_precios,
            filtrar_tabla_exclusion_pdf,
            preparar_tabla_exclusion_pdf,
            preparar_tabla_listas_precios,
        )

        df_listas = preparar_tabla_listas_precios(self.crear_dataframe_listas())
        df_calculado = calcular_listas_precios(df_listas, 2.0, 1.5)
        tabla_exclusion = preparar_tabla_exclusion_pdf(df_calculado, {1: False})

        self.assertEqual(
            filtrar_tabla_exclusion_pdf(tabla_exclusion, nombre="producto b")[
                "SKU"
            ].tolist(),
            ["SKU-B"],
        )
        self.assertEqual(
            filtrar_tabla_exclusion_pdf(tabla_exclusion, sku="sku-a")[
                "Nombre"
            ].tolist(),
            ["Producto A"],
        )
        self.assertEqual(
            filtrar_tabla_exclusion_pdf(tabla_exclusion, marca="marca 2")[
                "Incluir en PDF"
            ].tolist(),
            [False],
        )

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None, "reportlab no está instalado"
    )
    def test_pdf_filtra_sin_costo_y_no_mezcla_columnas(self):
        from app import (
            calcular_listas_precios,
            filtrar_lista_para_pdf,
            generar_pdf_lista_precios,
            preparar_tabla_listas_precios,
        )

        df_listas = preparar_tabla_listas_precios(self.crear_dataframe_listas())
        df_calculado = calcular_listas_precios(df_listas, 2.0, 1.5)
        df_pdf = filtrar_lista_para_pdf(df_calculado, "Marca 1")
        pdf = generar_pdf_lista_precios(
            df_calculado,
            "Minorista",
            "Pie de prueba",
            "Marca 1",
        )

        self.assertEqual(len(df_pdf), 1)
        self.assertGreater(len(pdf), 1000)
        self.assertTrue(pdf.startswith(b"%PDF"))

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None, "reportlab no está instalado"
    )
    def test_pdf_lista_precios_soporta_logo_ausente_y_nombres_largos(self):
        from app import (
            calcular_listas_precios,
            generar_pdf_lista_precios,
            preparar_tabla_listas_precios,
        )

        df_listas = preparar_tabla_listas_precios(self.crear_dataframe_listas())
        df_listas.loc[0, "Nombre"] = (
            "Producto natural con nombre extremadamente largo para validar que "
            "la celda de Nombre ajusta el texto sin invadir Marca ni SKU"
        )
        df_calculado = calcular_listas_precios(df_listas, 2.0, 1.5)

        pdf_minorista_sin_logo = generar_pdf_lista_precios(
            df_calculado,
            "Minorista",
            "Pie de prueba",
            "Marca 1",
            logo_path="assets/logo_inexistente.png",
        )
        pdf_mayorista_sin_logo = generar_pdf_lista_precios(
            df_calculado,
            "Mayorista",
            "Pie de prueba",
            "Marca 1",
            logo_path="assets/logo_inexistente.png",
        )

        self.assertGreater(len(pdf_minorista_sin_logo), 1000)
        self.assertGreater(len(pdf_mayorista_sin_logo), 1000)
        self.assertTrue(pdf_minorista_sin_logo.startswith(b"%PDF"))
        self.assertTrue(pdf_mayorista_sin_logo.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
