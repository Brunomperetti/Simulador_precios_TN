# Simulador de precios para Tienda Nube

App local/online hecha con Streamlit para:

- Subir CSV exportado desde Tienda Nube.
- Editar costos vacíos o existentes.
- Aplicar multiplicador por producto.
- Aplicar reglas masivas por marca.
- Calcular nuevo precio.
- Descargar el CSV completo listo para volver a importar en Tienda Nube.
- Descargar un CSV mínimo recomendado para actualizar precios, conservando identificador, nombre y propiedades de variantes.
- Validar nombres, identificadores y cantidad de precios realmente modificados antes de exportar.

## Ejecutar localmente

1. Instalar Python.
2. Abrir terminal dentro de esta carpeta.
3. Ejecutar:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy en Streamlit Cloud

1. Subir estos archivos a un repositorio de GitHub.
2. Entrar a https://streamlit.io/cloud
3. Crear nueva app apuntando a `app.py`.
4. Compartir el link con el cliente.

## Archivos

- `app.py`: aplicación principal.
- `requirements.txt`: dependencias necesarias.
- `README.md`: instrucciones.
