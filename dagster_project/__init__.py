"""
MyM Waffles - Dagster project.
"""
from dagster import Definitions, load_assets_from_modules
from dagster_project import assets
from dagster_project.dbt import dbt_models, dbt_resource
from dagster_project.schedules import daily_schedule, daily_refresh_job

python_assets = load_assets_from_modules([assets])

defs = Definitions(
    assets=[*python_assets, dbt_models],
    resources={"dbt": dbt_resource},
    jobs=[daily_refresh_job],
    schedules=[daily_schedule],
)