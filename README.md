# Generador .vsmeta para Synology Video Station

Este proyecto en Python permite generar automáticamente archivos de metadatos `.vsmeta` que Synology Video Station utiliza para mostrar información de las películas en tu biblioteca multimedia.

El script analiza los nombres de tus archivos de video, deduce el título y el año de la película, consulta la base de datos de **TMDb (The Movie Database)**, descarga los pósters y fondos directamente a memoria, y crea un archivo `.vsmeta` al lado de cada video.

## Características

- **Soporte de Rutas UNC:** Diseñado para funcionar directamente con rutas de red de Windows (ej. `\\192.168.1.2\video`).
- **Escaneo Inteligente:** Permite pasar tanto la ruta de un archivo de video individual como una carpeta completa.
- **Evita Duplicados:** Al escanear una carpeta, salta automáticamente los videos que ya disponen de su archivo `.vsmeta` (a menos que uses el flag `--force`).
- **Limpieza de Nombres:** Elimina automáticamente del nombre del archivo etiquetas como `[BluRay Rip]`, `[AC3 5.1 Español Castellano]`, reemplaza puntos/guiones bajos con espacios y extrae el año.
- **Sin Archivos Temporales:** Las imágenes se descargan y se inyectan en el archivo binario final directamente desde la memoria, sin dejar imágenes JPG huérfanas en el disco.
- **Monkeypatch para Windows:** Soluciona un error nativo de la librería `vsmetaEncoder` que impide su uso en Windows con fechas anteriores a 1970.

## Requisitos y Preparación

1. **Python 3.11+** debe estar instalado.
2. Abre una terminal (PowerShell 7 recomendado) y sitúate en esta carpeta:
   ```powershell
   cd "C:\Users\pming\Documents\Mis Fuentes\python\vsvideo"
   ```
3. Activa el entorno virtual:
   ```powershell
   .venv\Scripts\Activate.ps1
   ```

El entorno virtual y las dependencias ya están instalados y configurados.

### Configuración de credenciales (`.env`)
Dado que el archivo `.env` contiene información sensible (tu clave API), este se encuentra excluido del repositorio de Git. 

Si clonas este proyecto en un nuevo equipo, deberás:
1. Duplicar el archivo `.env.example` y renombrar la copia como `.env`.
2. Abrir el archivo `.env` y rellenar tu clave API de TMDb en la variable `TMDB_API_KEY`:
   ```ini
   TMDB_API_KEY=tu_clave_de_tmdb_aqui
   TMDB_LANGUAGE=es-ES
   ```

## Uso del Script

Puedes ejecutar el script usando Python desde tu terminal de PowerShell 7:

```powershell
python vsvideo.py "RUTA_DE_VIDEO_O_CARPETA" [OPCIONES]
```

### Argumentos y Opciones

- `target`: (Requerido) Ruta del archivo de video o de la carpeta. Soporta rutas de red UNC.
- `-h`, `--help`: Muestra la ayuda en pantalla con todas las opciones disponibles.
- `-f`, `--force`: Fuerza la recreación del archivo `.vsmeta` aunque ya exista uno al lado del video.
- `-r`, `--recursive`: Escanea subcarpetas de forma recursiva (si el target es un directorio).
- `-i`, `--interactive`: Activa el modo interactivo para que, si hay dudas o no hay resultados en TMDb, puedas buscar con otro nombre o seleccionar el resultado correcto manualmente de forma interactiva.
- `-v`, `--verbose`: Muestra información en detalle de las consultas a TMDb y los pasos del proceso.
- `--lang`: Idioma para los metadatos de TMDb (por defecto `es-ES`).
- `--api-key`: Permite sobrescribir la clave API de TMDb temporalmente.
- `--clean-invalid`: Solo busca y elimina archivos `.vsmeta` inválidos (de tamaño <= 1KB o corruptos) y finaliza de inmediato.

---

### Ejemplos Prácticos

#### 1. Procesar un archivo individual en la red UNC
```powershell
python vsvideo.py "\\192.168.1.2\video\0_1 Ciencia Ficción\AlienVsPredator2 [BluRay Rip][AC3 5.1 Español Castellano].avi" -v
```

#### 2. Escanear una carpeta completa en la red (omitiendo existentes)
```powershell
python vsvideo.py "\\192.168.1.2\video\0_1 Ciencia Ficción"
```

#### 3. Escanear en modo interactivo (te preguntará si tiene dudas con nombres o si no encuentra resultados)
```powershell
python vsvideo.py "\\192.168.1.2\video\0_1 Ciencia Ficción" -i
```

#### 4. Escanear de forma recursiva y forzar la actualización de todos los metadatos
```powershell
python vsvideo.py "\\192.168.1.2\video\0_1 Ciencia Ficción" --recursive --force -v
```

#### 5. Limpiar archivos .vsmeta inválidos o dañados de forma recursiva
```powershell
python vsvideo.py "\\192.168.1.2\video\0_1 Ciencia Ficción" --clean-invalid --recursive
```

---

## Verificación de Resultados

Puedes verificar el archivo `.vsmeta` generado en tu biblioteca de Video Station, o bien puedes usar un script en Python para decodificarlo e imprimirlo en consola.
