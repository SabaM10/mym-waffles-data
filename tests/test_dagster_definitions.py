"""
Tests de integración de la definición de Dagster.
Valida que el objeto Definitions carga sin errores y
contiene los assets, jobs y schedules esperados.
"""
from dagster_project import defs


def test_definitions_loads_without_errors():
    """La definición se importa sin explotar."""
    assert defs is not None


def test_assets_present():
    """Los assets esperados están declarados."""
    graph = defs.resolve_asset_graph()
    paths = [k.path for k in graph.get_all_asset_keys()]
    
    # Assets Python de ingestion (fusionados con sources de dbt)
    assert ["raw", "pedidos"] in paths
    assert ["raw", "precios"] in paths
    
    # Mart principal de semana 6
    assert ["marts", "rpt_ventas_semanales"] in paths


def test_schedule_declared():
    """El schedule diario está declarado."""
    schedule_names = [s.name for s in defs.schedules]
    assert "daily_refresh_schedule" in schedule_names


def test_daily_job_declared():
    """El job asociado al schedule está declarado."""
    job_names = [j.name for j in defs.jobs]
    assert "daily_refresh" in job_names