import unittest
from io import StringIO

import pandas as pd

from app import (
    construir_dataframe_exportacion,
    generar_csv_descarga,
    obtener_metricas_csv,
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

        self.assertEqual(df_exportado.loc[1, "Precio"], "21,906.60")
        self.assertEqual(df_exportado.loc[2, "Precio"], df_original.loc[2, "Precio"])

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

    def test_metricas_csv_cuenta_productos_unicos_y_variantes(self):
        filas, productos_unicos, variantes = obtener_metricas_csv(
            self.crear_csv_original()
        )

        self.assertEqual(filas, 4)
        self.assertEqual(productos_unicos, 3)
        self.assertEqual(variantes, 1)


if __name__ == "__main__":
    unittest.main()
