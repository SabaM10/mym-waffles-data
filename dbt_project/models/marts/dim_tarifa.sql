-- ============================================================
-- dim_tarifa: dimensión de tarifas con SCD Type 2.
-- ============================================================
-- Una fila por (tarifa × período de vigencia).
-- Fuente: seed precios_historicos.csv.
-- Cada versión histórica tiene su propio tarifa_id.
-- ============================================================

with historico as (

    select * from {{ ref('precios_historicos') }}

),

con_calculos as (

    select
        segmento,
        producto_desc,
        unidades_pack,
        precio_venta_ars,
        costo_pack_ars,

        -- Precio por unidad (útil para pedidos que no matchean pack exacto)
        cast(precio_venta_ars as decimal(12, 4)) / unidades_pack as precio_unitario_ars,

        -- Margen bruto en pesos
        precio_venta_ars - costo_pack_ars as margen_bruto_ars,

        -- Vigencia
        valid_from,
        valid_to,

        -- Boolean calculado: es la versión actualmente vigente?
        case when valid_to is null then true else false end as es_current

    from historico

),

dim_tarifa as (

    select
        -- Surrogate key: hash de (segmento + producto + pack + valid_from)
        -- Cada versión histórica tiene su propio ID
        md5(concat_ws('|',
            segmento,
            producto_desc,
            unidades_pack::varchar,
            valid_from::varchar
        )) as tarifa_id,

        segmento,
        producto_desc,
        unidades_pack,
        precio_venta_ars,
        costo_pack_ars,
        precio_unitario_ars,
        margen_bruto_ars,
        valid_from,
        valid_to,
        es_current,

        -- Metadata
        current_timestamp as created_at

    from con_calculos

)

select * from dim_tarifa
order by segmento, producto_desc, unidades_pack, valid_from