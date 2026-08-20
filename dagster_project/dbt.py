"""
Assets de dbt.
Auto-genera un asset por cada modelo dbt del proyecto,
con dependencias leídas del manifest.
"""
from pathlib import Path
from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

# 1. Declarar el proyecto dbt
dbt_project = DbtProject(
    project_dir=Path("/workspace/dbt_project"),
)
dbt_project.prepare_if_dev()

# 2. Resource para ejecutar comandos dbt
dbt_resource = DbtCliResource(
    project_dir=dbt_project,
    profiles_dir="/workspace/dbt_project",  # ← agregar esta línea
)

# 3. Assets auto-generados desde el manifest
@dbt_assets(manifest=dbt_project.manifest_path)
def dbt_models(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()