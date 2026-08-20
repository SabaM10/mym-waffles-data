"""
Schedule diario del pipeline completo.
Deshabilitado por default: se activa cuando el pipeline
corra en un server 24/7 (hoy vive en máquina local).
"""
from dagster import (
    ScheduleDefinition,
    DefaultScheduleStatus,
    AssetSelection,
    define_asset_job,
)

# Job que materializa TODOS los assets
daily_refresh_job = define_asset_job(
    name="daily_refresh",
    selection=AssetSelection.all(),
)

# Schedule diario a las 6 AM, deshabilitado por default
daily_schedule = ScheduleDefinition(
    job=daily_refresh_job,
    cron_schedule="0 6 * * *",
    default_status=DefaultScheduleStatus.STOPPED,
)