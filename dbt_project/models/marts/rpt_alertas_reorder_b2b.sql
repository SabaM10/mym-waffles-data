-- rpt_alertas_reorder_b2b
-- Grain: una fila por cliente B2B analizable.
-- Propósito: alimentar el dashboard "Alertas B2B" de Metabase (W10).
-- Consumido por: dashboard operativo de reorder.
--
-- Interpretación de ratio_atraso:
--   < 1.0  : cliente al día (dentro del umbral esperado)
--   = 1.0  : justo sobre el umbral
--   > 1.0  : en alerta (X veces el umbral)
--   >= 2.0 : alerta severa (>= 2x el umbral)

select
    cliente_id,
    cliente_canonico,

    -- Métricas de cadencia (heredadas de int_b2b_cadencia).
    total_pedidos,
    fecha_ultimo_pedido,
    intervalo_promedio_dias,
    intervalo_desvio_dias,
    umbral_alerta_dias,

    -- Métricas de atraso.
    dias_desde_ultimo_pedido,
    dias_desde_ultimo_pedido - umbral_alerta_dias   as dias_de_atraso,
    dias_desde_ultimo_pedido / umbral_alerta_dias   as ratio_atraso,

    -- Flag operativo. Redundante con ratio_atraso > 1, pero explícito
    -- para consumo directo desde Metabase sin lógica adicional.
    alerta_reorder

from {{ ref('int_b2b_cadencia') }}