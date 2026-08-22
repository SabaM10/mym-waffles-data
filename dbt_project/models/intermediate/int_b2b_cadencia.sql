-- int_b2b_cadencia
-- Grain: una fila por cliente B2B analizable.
-- Filtros: tipo_cliente = 'B2B', es_ambiguo = FALSE, total_pedidos >= 4.
-- Propósito: base rule-based para detección de reorder atrasado (W10).
-- Umbral de alerta parametrizable vía var 'umbral_alerta_desvios_b2b'.

with pedidos_b2b as (

    select
        fp.cliente_id,
        dc.cliente_canonico,
        fp.fecha_emision
    from {{ ref('fact_pedidos') }} fp
    inner join {{ ref('dim_cliente') }} dc
        on fp.cliente_id = dc.cliente_id
    where dc.tipo_cliente = 'B2B'
      and dc.es_ambiguo = false

),

intervalos as (

    select
        cliente_id,
        cliente_canonico,
        fecha_emision,
        fecha_emision - lag(fecha_emision) over (
            partition by cliente_id
            order by fecha_emision
        ) as dias_desde_pedido_previo
    from pedidos_b2b

),

cadencia_por_cliente as (

    select
        cliente_id,
        cliente_canonico,
        count(*)                                        as total_pedidos,
        max(fecha_emision)                              as fecha_ultimo_pedido,
        avg(dias_desde_pedido_previo)                   as intervalo_promedio_dias,
        stddev_samp(dias_desde_pedido_previo)           as intervalo_desvio_dias,
        current_date - max(fecha_emision)               as dias_desde_ultimo_pedido
    from intervalos
    group by cliente_id, cliente_canonico
    having count(*) >= 4

)

select
    cliente_id,
    cliente_canonico,
    total_pedidos,
    fecha_ultimo_pedido,
    intervalo_promedio_dias,
    intervalo_desvio_dias,
    dias_desde_ultimo_pedido,

    intervalo_promedio_dias
        + ({{ var('umbral_alerta_desvios_b2b') }} * coalesce(intervalo_desvio_dias, 0))
        as umbral_alerta_dias,

    dias_desde_ultimo_pedido > (
        intervalo_promedio_dias
        + ({{ var('umbral_alerta_desvios_b2b') }} * coalesce(intervalo_desvio_dias, 0))
    ) as alerta_reorder

from cadencia_por_cliente