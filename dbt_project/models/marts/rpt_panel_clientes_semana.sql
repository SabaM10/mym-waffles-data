-- rpt_panel_clientes_semana
-- Grain: una fila por cliente B2B analizable (los mismos de rpt_alertas_reorder_b2b).
-- Propósito: la tabla "quién tendría que pedir esta semana" de la vista
-- "La semana" del panel. Junta la regla (rpt_alertas_reorder_b2b), la
-- probabilidad (mart_b2b_reorder_probabilistico) y lo que suele pedir cada
-- cliente, para que el panel no tenga que calcular nada.
--
-- estado_semana:
--   'atrasado' : la regla de W10 ya disparó (alerta_reorder).
--   'le_toca'  : todavía no está atrasado, pero la fecha esperada del
--                próximo pedido cae dentro de esta semana (lunes a domingo).
--   'al_dia'   : el próximo pedido esperado es de la semana que viene o después.

with alertas as (

    select * from {{ ref('rpt_alertas_reorder_b2b') }}

),

probabilistico as (

    select
        cliente_id,
        probabilidad_reorder_ya,
        confianza_estimacion
    from {{ ref('mart_b2b_reorder_probabilistico') }}

),

-- Cuánto pide en promedio cada cliente.
volumen as (

    select
        cliente_id,
        avg(cantidad_total) as unidades_promedio
    from {{ ref('fact_pedidos') }}
    group by cliente_id

),

-- El SKU que más unidades le compró cada cliente (desempate alfabético
-- para que el resultado sea determinístico).
producto_por_cliente as (

    select
        fp.cliente_id,
        fi.masa,
        fi.sabor,
        sum(fi.cantidad) as unidades
    from {{ ref('fact_pedido_items') }} fi
    inner join {{ ref('fact_pedidos') }} fp
        on fi.pedido_id = fp.pedido_id
    where fi.masa is not null and fi.sabor is not null
    group by fp.cliente_id, fi.masa, fi.sabor

),

producto_habitual as (

    select
        cliente_id,
        masa as masa_habitual,
        sabor as sabor_habitual
    from producto_por_cliente
    qualify row_number() over (
        partition by cliente_id
        order by unidades desc, masa, sabor
    ) = 1

),

base as (

    select
        a.cliente_id,
        a.cliente_canonico,
        a.total_pedidos,
        a.fecha_ultimo_pedido,
        a.intervalo_promedio_dias,
        a.dias_desde_ultimo_pedido,
        a.dias_de_atraso,
        a.ratio_atraso,
        a.alerta_reorder,
        p.probabilidad_reorder_ya,
        p.confianza_estimacion,
        v.unidades_promedio,
        h.masa_habitual,
        h.sabor_habitual,

        -- Fecha en que, según su cadencia, le tocaría el próximo pedido.
        a.fecha_ultimo_pedido
            + cast(round(a.intervalo_promedio_dias) as integer) as fecha_proximo_esperado,

        -- Domingo de la semana en curso (las semanas arrancan el lunes).
        cast(date_trunc('week', current_date) as date) + 6 as domingo_semana_actual

    from alertas a
    left join probabilistico p on a.cliente_id = p.cliente_id
    left join volumen v on a.cliente_id = v.cliente_id
    left join producto_habitual h on a.cliente_id = h.cliente_id

)

select
    cliente_id,
    cliente_canonico,
    total_pedidos,
    fecha_ultimo_pedido,
    intervalo_promedio_dias,
    dias_desde_ultimo_pedido,
    dias_de_atraso,
    ratio_atraso,
    alerta_reorder,
    probabilidad_reorder_ya,
    confianza_estimacion,
    unidades_promedio,
    masa_habitual,
    sabor_habitual,
    fecha_proximo_esperado,

    case
        when alerta_reorder then 'atrasado'
        when fecha_proximo_esperado <= domingo_semana_actual then 'le_toca'
        else 'al_dia'
    end as estado_semana

from base
