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

    # Semana 13: forecast por SKU, clientes de la semana y publicación al panel
    assert ["marts", "mart_forecast_semanal_sku"] in paths
    assert ["marts", "rpt_panel_clientes_semana"] in paths
    assert ["serving", "publicar_panel"] in paths


def test_publicar_panel_depende_de_los_marts():
    """El asset que publica corre después de los tres marts que lee."""
    from dagster import AssetKey

    graph = defs.resolve_asset_graph()
    padres = graph.get(AssetKey(["serving", "publicar_panel"])).parent_keys
    assert AssetKey(["marts", "mart_forecast_semanal"]) in padres
    assert AssetKey(["marts", "mart_forecast_semanal_sku"]) in padres
    assert AssetKey(["marts", "rpt_panel_clientes_semana"]) in padres


def test_schedule_declared():
    """El schedule diario está declarado."""
    schedule_names = [s.name for s in defs.schedules]
    assert "daily_refresh_schedule" in schedule_names


def test_daily_job_declared():
    """El job asociado al schedule está declarado."""
    job_names = [j.name for j in defs.jobs]
    assert "daily_refresh" in job_names