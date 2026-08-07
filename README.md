# MyM Waffles — Data Platform

Pipeline de datos batch para **MyM Waffles**, negocio familiar de waffles congelados (B2C + B2B mayorista en AMBA). Ingesta desde Google Sheets, transforma con dbt, sirve dashboards con Metabase. Todo local, cero cloud, cero costo.

Proyecto de aprendizaje de data engineering con casos de uso reales del negocio.

## Casos de uso

1. **Reporte semanal de ventas** — visibilidad general del negocio.
2. **Forecast semanal de demanda** — estadística clásica sobre serie histórica.
3. **Detección de anomalías de reorder en clientes B2B** — el dolor real: 10-15 clientes con cadencias distintas que a ojo se pierden.

## Arquitectura

```
Google Sheets → Dagster (extract via gspread + Polars)
             → DuckDB (raw)
             → dbt (staging → intermediate → marts)
             → Metabase
```

Ver `docs/arquitectura.md` para el diagrama detallado.

## Stack

| Capa | Herramienta |
|---|---|
| Ingesta | Python 3.11 + Polars + gspread |
| Warehouse | DuckDB (archivo local) |
| Transformación | dbt-core con adapter duckdb |
| Orquestación | Dagster |
| Dashboard | Metabase |
| Contenedores | Docker Compose |
| Dependencias | uv |

## Quickstart

Requisitos: Docker Desktop, cuenta Google Cloud con Sheets API habilitada, service account con acceso lectura a las hojas.

```bash
# 1. Clonar el repo
git clone https://github.com/SabaM10/mym-waffles-data.git
cd mym-waffles-data

# 2. Configurar credenciales
cp .env.example .env
# Editar .env con IDs de Sheets reales
# Colocar credentials.json en ./secrets/

# 3. Levantar servicios
docker compose up -d

# 4. Materializar assets
docker compose exec dagster dagster asset materialize --select "*"
```

URLs una vez levantado:
- Dagster UI: http://localhost:3000
- Metabase: http://localhost:3001

## Estructura del repo

```
.
├── ingestion/                # Código Python de extract (Sheets → DuckDB raw)
├── dagster_project/          # Assets, schedules, jobs
├── dbt_project/              # Modelos SQL
│   ├── models/staging/
│   ├── models/intermediate/
│   ├── models/marts/
│   ├── seeds/                # client_name_mapping, tarifas iniciales
│   ├── tests/                # Tests SQL custom
│   └── macros/
├── tests/                    # pytest para código Python
├── docs/                     # Documentación técnica y de dominio
├── scripts/                  # One-offs: backfills, utilidades
├── data/                     # Archivo .duckdb (gitignored)
├── secrets/                  # credentials.json (gitignored)
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── CLAUDE.md                 # Instrucciones para Claude Code
└── README.md
```

## Estado

Proyecto en construcción activa. Roadmap de 12 semanas, un módulo por semana. Ver `docs/roadmap.md`.

- [x] Semana 1: Setup e infraestructura base
- [ ] Semana 2: Ingesta raw desde Sheets
- [ ] Semana 3: Parsing + normalización
- [ ] Semana 4: dbt setup + staging
- [ ] Semana 5: Dimensiones + seeds
- [ ] Semana 6: Facts + primeras métricas
- [ ] Semana 7: Dagster orquestación
- [ ] Semana 8: Metabase dashboards
- [ ] Semana 9: Forecast semanal
- [ ] Semana 10: Análisis B2B (detección de patrones)
- [ ] Semana 11: Backfill 2024-2025
- [ ] Semana 12: Polish + portfolio

## Fuera de scope (por ahora)

- Análisis de gastos y márgenes.
- Aging de cobranzas.
- Modelos ML de forecast.

## Contexto de dominio

MyM Waffles vende waffles congelados en 3 masas (Clásica, Integral, Proteica) con 4 sabores posibles (Dulce, Salado, Neutro, Oreo). Solo 8 combinaciones son SKUs válidos. El pricing es una rate card con 4 segmentos (Minorista, Promo, Mayorista, Proteico) y precios por tamaño de pack.

Ver `docs/pricing.md` para el detalle de la rate card y `docs/modelo.md` para el modelo dimensional.

## Licencia

Propietario. Los datos del negocio no están versionados en el repo.
