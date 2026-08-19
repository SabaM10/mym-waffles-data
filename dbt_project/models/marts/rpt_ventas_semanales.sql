-- ============================================================
-- rpt_ventas_semanales: mart de reporte semanal de ventas.
-- ============================================================
-- Agregación por semana con métricas clave del negocio.
-- Fuente: fact_pedidos + dim_fecha.
-- ============================================================

with pedidos as (

    select * from {{ ref('fact_pedidos') }}

),

fechas as (

    select fecha_id, fecha, año, mes_numero, nombre_mes, semana_del_año
    from {{ ref('dim_fecha') }}

),

clientes as (

    select cliente_id, cliente_canonico, tipo_cliente
    from {{ ref('dim_cliente') }}

),

pedidos_enriquecidos as (

    select
        p.pedido_id,
        p.precio_total_ars,
        p.cantidad_total,
        p.metodo_pago,
        p.pago_completado,
        p.entregado,
        f.año,
        f.semana_del_año,
        f.mes_numero,
        f.nombre_mes,
        c.tipo_cliente
    from pedidos p
    left join fechas f on p.fecha_emision_id = f.fecha_id
    left join clientes c on p.cliente_id = c.cliente_id

),

agregado as (

    select
        año,
        semana_del_año,
        mes_numero,
        nombre_mes,

        -- Métricas totales
        count(*) as total_pedidos,
        sum(cantidad_total) as total_unidades,
        sum(precio_total_ars) as total_facturado_ars,
        avg(precio_total_ars) as ticket_promedio_ars,

        -- Split B2B / B2C
        count(*) filter (where tipo_cliente = 'B2B') as pedidos_b2b,
        count(*) filter (where tipo_cliente = 'B2C') as pedidos_b2c,
        sum(precio_total_ars) filter (where tipo_cliente = 'B2B') as facturado_b2b_ars,
        sum(precio_total_ars) filter (where tipo_cliente = 'B2C') as facturado_b2c_ars,

        -- Estado
        count(*) filter (where pago_completado = true) as pedidos_pagados,
        count(*) filter (where entregado = true) as pedidos_entregados

    from pedidos_enriquecidos
    group by año, semana_del_año, mes_numero, nombre_mes

)

select * from agregado
order by año, semana_del_año