-- ============================================================
-- fact_pedidos: fact table de cabecera de pedidos.
-- ============================================================
-- Una fila por pedido con FKs a dimensiones y medidas totales.
-- Fuente: stg_pedidos, joineando con dim_cliente y dim_fecha.
-- ============================================================

with pedidos as (

    select * from {{ ref('stg_pedidos') }}

),

clientes_normalizados as (

    select distinct
        cliente_raw,
        strip_accents(
            regexp_replace(trim(lower(cliente_raw)), '\s+', ' ', 'g')
        ) as nombre_normalizado
    from pedidos

),

dim_cliente as (

    select * from {{ ref('dim_cliente') }}

),

mapping_cliente as (

    select * from {{ ref('client_name_mapping') }}

),

dim_fecha as (

    select fecha, fecha_id from {{ ref('dim_fecha') }}

),

pedidos_con_fks as (

    select
        p.pedido_id,
        
        -- FK a dim_cliente vía mapping y canónico
        dc.cliente_id,
        
        -- FKs a dim_fecha
        df_emision.fecha_id as fecha_emision_id,
        df_entrega.fecha_id as fecha_entrega_id,
        
        -- Atributos degenerados y medidas
        p.metodo_pago,
        p.cantidad_total,
        p.precio_total_ars,
        p.favor_envio_ars,
        p.seña_ars,
        p.pago_completado,
        p.entregado,
        
        -- Fechas originales por si son útiles
        p.fecha_emision,
        p.fecha_entrega

    from pedidos p
    
    -- Normalizar cliente_raw para join con mapping
    left join clientes_normalizados cn on p.cliente_raw = cn.cliente_raw
    left join mapping_cliente mc on cn.nombre_normalizado = mc.nombre_normalizado
    left join dim_cliente dc
    on {{ cliente_canonico_fallback('mc.cliente_canonico', 'cn.nombre_normalizado') }} = dc.cliente_canonico
    
    -- FKs de fecha
    left join dim_fecha df_emision on p.fecha_emision = df_emision.fecha
    left join dim_fecha df_entrega on p.fecha_entrega = df_entrega.fecha

)

select * from pedidos_con_fks