"""
MyM Waffles — Dagster project.

Este módulo expone `defs` (Definitions) con todos los assets, jobs,
schedules y sensors del pipeline.

En semana 1 arranca vacío para verificar que el container levanta.
Semana 2+ va agregando assets reales.
"""

from dagster import Definitions

# Stub inicial: sin assets todavía.
# Cuando agregues assets en semana 2, la firma va a verse así:
#
#     from dagster_project.assets import raw_pedidos, raw_precios
#
#     defs = Definitions(
#         assets=[raw_pedidos, raw_precios],
#         schedules=[...],
#         resources={...},
#     )

defs = Definitions()
