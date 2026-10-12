"""Regresiones del multiplicador masivo por marcas y del CSV de Tienda Nube."""

import unittest

import pandas as pd

from app import (
    aplicar_multiplicador_a_marcas,
    construir_dataframe_exportacion,
    preparar_tabla_trabajo,
    recalcular_precios,
    marcas_seleccionadas_por_tilde,
    todas_las_marcas_estan_seleccionadas,
)


class TestMultiplicadorMultimarca(unittest.TestCase):
    def setUp(self):
        self.original = pd.DataFrame(
            {
                "Nombre": ["Pampa 1", "Natufarma", "Ocean", "Pampa variante", "Sin costo"],
                "Marca": ["Pampa", "Natufarma", "Ocean", "Pampa", "Ocean"],
                "SKU": ["P1", "N1", "O1", "P1-V", "O2"],
                "Precio": ["150", "270", "350", "280", "60"],
                "Costo": ["100", "100", "100", "100", ""],
                "Otro campo": ["a", "b", "c", "d", "e"],
            }
        )
        self.tabla = preparar_tabla_trabajo(self.original)
        self.costos_originales = self.tabla["Costo"].copy()

    def test_tildar_todas_marca_todas_las_opciones(self):
        marcas = ["Pampa", "Natufarma", "Ocean"]
        seleccion = marcas_seleccionadas_por_tilde(marcas, True)
        self.assertEqual(seleccion, marcas)
        self.assertTrue(todas_las_marcas_estan_seleccionadas(marcas, seleccion))

    def test_quitar_excepciones_no_elimina_las_56_restantes(self):
        marcas = [f"Marca {n:02d}" for n in range(62)]
        seleccion = marcas_seleccionadas_por_tilde(marcas, True)
        seleccion.remove("Marca 02")
        seleccion.remove("Marca 47")
        self.assertEqual(len(seleccion), 60)
        self.assertFalse(todas_las_marcas_estan_seleccionadas(marcas, seleccion))
        self.assertIn("Marca 01", seleccion)
        self.assertNotIn("Marca 02", seleccion)

    def test_destildar_todas_limpia_la_seleccion(self):
        marcas = ["Pampa", "Natufarma"]
        self.assertEqual(marcas_seleccionadas_por_tilde(marcas, False), [])
        self.assertFalse(todas_las_marcas_estan_seleccionadas(marcas, []))

    def test_seleccion_parcial_no_marca_todas(self):
        marcas = ["Pampa", "Natufarma", "Ocean"]
        self.assertFalse(
            todas_las_marcas_estan_seleccionadas(marcas, ["Pampa", "Ocean"])
        )
        self.assertTrue(
            todas_las_marcas_estan_seleccionadas(
                marcas, ["Ocean", "Pampa", "Natufarma"]
            )
        )

    def test_cero_marcas_no_equivale_a_todas(self):
        self.assertFalse(todas_las_marcas_estan_seleccionadas([], []))
        self.assertEqual(marcas_seleccionadas_por_tilde([], True), [])

    def test_masivo_23_excluye_marcas_removidas_del_selector(self):
        marcas = sorted(self.original["Marca"].unique())
        elegidas = marcas_seleccionadas_por_tilde(marcas, True)
        elegidas.remove("Natufarma")
        resultado, indices = aplicar_multiplicador_a_marcas(
            self.tabla, elegidas, 2.3
        )
        self.assertEqual(indices, [0, 2, 3, 4])
        self.assertEqual(resultado.loc[1, "Multiplicador"], 1.0)
        self.assertEqual(resultado.loc[0, "Multiplicador"], 2.3)
        exportado = construir_dataframe_exportacion(
            self.original, resultado, self.costos_originales, set(indices)
        )
        self.assertEqual(
            exportado.loc[1].tolist(), self.original.loc[1].tolist()
        )

    def test_una_marca_incluye_todas_sus_variantes(self):
        resultado, indices = aplicar_multiplicador_a_marcas(self.tabla, ["Pampa"], 2.0)
        self.assertEqual(indices, [0, 3])
        self.assertEqual(resultado.loc[0, "Nuevo Precio"], 200.0)
        self.assertEqual(resultado.loc[3, "Nuevo Precio"], 200.0)
        self.assertEqual(resultado.loc[1, "Multiplicador"], 1.0)
        self.assertEqual(resultado.loc[2, "Multiplicador"], 1.0)

    def test_varias_marcas_sin_afectar_las_excluidas(self):
        resultado, indices = aplicar_multiplicador_a_marcas(
            self.tabla, ["Pampa", "Natufarma"], 2.5
        )
        self.assertEqual(indices, [0, 1, 3])
        self.assertTrue((resultado.loc[[0, 1, 3], "Multiplicador"] == 2.5).all())
        self.assertTrue((resultado.loc[[2, 4], "Multiplicador"] == 1.0).all())

    def test_todas_las_marcas(self):
        marcas = sorted(self.tabla["Marca"].unique().tolist())
        resultado, indices = aplicar_multiplicador_a_marcas(self.tabla, marcas, 3.0)
        self.assertEqual(indices, [0, 1, 2, 3, 4])
        self.assertTrue((resultado["Multiplicador"] == 3.0).all())
        self.assertTrue(pd.isna(resultado.loc[4, "Nuevo Precio"]))

    def test_sin_marcas_no_modifica_ni_aplica(self):
        resultado, indices = aplicar_multiplicador_a_marcas(self.tabla, [], 2.0)
        self.assertEqual(indices, [])
        pd.testing.assert_frame_equal(resultado, self.tabla)
        self.assertIsNot(resultado, self.tabla)

    def test_una_segunda_aplicacion_conserva_otros_multiplicadores(self):
        primera, _ = aplicar_multiplicador_a_marcas(self.tabla, ["Ocean"], 3.0)
        segunda, indices = aplicar_multiplicador_a_marcas(primera, ["Pampa"], 2.0)
        self.assertEqual(indices, [0, 3])
        self.assertEqual(segunda.loc[2, "Multiplicador"], 3.0)
        self.assertEqual(segunda.loc[0, "Multiplicador"], 2.0)

    def test_original_y_costos_permanecen_intactos(self):
        original_trabajo = self.tabla.copy(deep=True)
        resultado, _ = aplicar_multiplicador_a_marcas(self.tabla, ["Pampa"], 4.0)
        pd.testing.assert_frame_equal(self.tabla, original_trabajo)
        pd.testing.assert_series_equal(resultado["Costo"], self.tabla["Costo"])

    def test_exportacion_preserva_columnas_y_filas_excluidas(self):
        resultado, indices = aplicar_multiplicador_a_marcas(
            self.tabla, ["Pampa"], 2.0
        )
        exportado = construir_dataframe_exportacion(
            self.original, resultado, self.costos_originales, set(indices)
        )
        self.assertEqual(exportado.columns.tolist(), self.original.columns.tolist())
        self.assertEqual(exportado.loc[0, "Precio"], "200.00")
        self.assertEqual(exportado.loc[3, "Precio"], "200.00")
        for indice in [1, 2, 4]:
            self.assertEqual(
                exportado.loc[indice].tolist(), self.original.loc[indice].tolist()
            )
        self.assertEqual(exportado["Otro campo"].tolist(), self.original["Otro campo"].tolist())


if __name__ == "__main__":
    unittest.main()
