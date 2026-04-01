# inspect_remote_gis — Guía de uso

Management command para inspeccionar una PostGIS remota y generar el catálogo de capas `AGENTS_GIS_LAYERS`.

---

## 1. Configurar la BD remota en `.env` o `.env.local`

```env
GIS_REMOTE_DB_HOST=mi-servidor.example.com
GIS_REMOTE_DB_PORT=5432
GIS_REMOTE_DB_NAME=mi_bd_gis
GIS_REMOTE_DB_USER=usuario
# GIS_REMOTE_DB_PASSWORD=        # omitir si no hay contraseña
# GIS_REMOTE_DB_SSLMODE=         # omitir para no usar SSL

AGENTS_GIS_DB_ALIAS=gis_remote  # activa el uso de la BD remota en las tools
AGENTS_GIS_SCHEMA=atom           # esquema PostgreSQL donde están las capas
```

---

## 2. Inspeccionar (solo mostrar, sin guardar)

```bash
python manage.py inspect_remote_gis
```

Usa el alias `gis_remote` por defecto y el esquema `public`.

---

## 3. Inspeccionar y guardar el catálogo

```bash
python manage.py inspect_remote_gis --save
```

Genera `gis_layers_catalog.json` en `BASE_DIR`. Al reiniciar el servidor,
`settings.py` lo carga automáticamente como `AGENTS_GIS_LAYERS`.

---

## 4. Especificar alias de BD y esquema

```bash
python manage.py inspect_remote_gis --db-alias gis_remote --schema mi_esquema --save
```

---

## 5. Filtrar tablas

```bash
# Incluir solo ciertas tablas
python manage.py inspect_remote_gis --include cables nodos zonas --save

# Excluir tablas del catálogo
python manage.py inspect_remote_gis --exclude spatial_ref_sys geography_columns --save
```

---

## 6. Flujo completo

```bash
# 1. Configurar credenciales en .env.local
# 2. Inspeccionar y guardar
python manage.py inspect_remote_gis --db-alias gis_remote --schema public --save

# 3. Reiniciar el servidor
python manage.py runserver

# 4. Verificar capas disponibles vía API
curl http://127.0.0.1:8000/api/tools/ -H "Authorization: Token $TOKEN"
```

---

## Variables de entorno de referencia

| Variable | Descripción | Default |
|---|---|---|
| `GIS_REMOTE_DB_HOST` | Host de la PostGIS remota | *(vacío, desactivado)* |
| `GIS_REMOTE_DB_PORT` | Puerto | `5432` |
| `GIS_REMOTE_DB_NAME` | Nombre de la base de datos | *(vacío)* |
| `GIS_REMOTE_DB_USER` | Usuario | *(vacío)* |
| `GIS_REMOTE_DB_PASSWORD` | Contraseña (opcional si no hay auth) | *(vacío)* |
| `GIS_REMOTE_DB_SSLMODE` | Modo SSL (`off`, `prefer`, `require`) | `off` |

> **Nota SRID:** el comando detecta automáticamente el SRID de cada capa desde `geometry_columns` y lo guarda en el campo `srid` del catálogo. Las herramientas GIS usan ese valor para transformar las coordenadas 4326 al SRID de la capa y viceversa.
| `AGENTS_GIS_DB_ALIAS` | Alias Django que usan las tools GIS | `default` |
| `AGENTS_GIS_SCHEMA` | Esquema PostgreSQL de las capas GIS | `public` |
| `DB_HOST` | Host de la BD Django principal | `127.0.0.1` |
| `DB_PORT` | Puerto de la BD Django principal | `5433` |
| `DB_NAME` | Nombre BD Django principal | `geoagents` |
| `DB_USER` | Usuario BD Django principal | `geoagents` |
| `DB_PASSWORD` | Contraseña BD Django principal | `geoagents` |
