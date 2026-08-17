-- ============================================================
-- stg_pedidos: pedidos tipados y limpiados desde raw.pedidos.
-- ============================================================
-- Renombra columnas a snake_case, tipa cantidades/fechas/booleans,
-- limpia formato de precios (elimina '$' y '.' de miles).
-- El campo PEDIDO se mantiene como string; se parsea en int_pedido_items.
-- ============================================================

with source as (

    select * from {{ source('raw', 'pedidos') }}

),

renombrado as (

    select
        -- Identificación
        trim(CUIT) as cuit,
        trim(CLIENTE) as cliente_raw,
        trim(PEDIDO) as pedido_string,

        -- Cantidades y precios (todavía como string, se tipan abajo)
        CANTIDAD as cantidad_str,
        PRECIO as precio_total_str,
        "A FAVOR ENVIO" as favor_envio_str,
        SEÑA as seña_str,

        -- Método de pago
        case
            when upper(trim(PAGO)) = 'MP' then 'MercadoPago'
            else trim(PAGO)
        end as metodo_pago,

        -- Fechas (string por ahora)
        EMISIÓN as fecha_emision_str,
        ENTREGA as fecha_entrega_str,

        -- Booleans (string por ahora)
        "PAGO COMPLETADO" as pago_completado_str,
        ENTREGADO as entregado_str,

        -- Metadata
        ingested_at

    from source

),

tipado as (

    select
        cuit,
        cliente_raw,
        pedido_string,
        metodo_pago,
        ingested_at,

        -- Cantidad total: cast a INTEGER
        try_cast(cantidad_str as integer) as cantidad_total,

        -- Precios: quitar '$' y '.', cambiar ',' por '.', cast a DECIMAL
        try_cast(
            replace(replace(replace(precio_total_str, '$', ''), '.', ''), ',', '.')
            as decimal(12, 2)
        ) as precio_total_ars,

        try_cast(
            replace(replace(replace(favor_envio_str, '$', ''), '.', ''), ',', '.')
            as decimal(12, 2)
        ) as favor_envio_ars,

        try_cast(
            replace(replace(replace(seña_str, '$', ''), '.', ''), ',', '.')
            as decimal(12, 2)
        ) as seña_ars,

        -- Fechas: parse dd/mm/yyyy
        try_cast(strptime(fecha_emision_str, '%d/%m/%Y') as date) as fecha_emision,
        try_cast(strptime(fecha_entrega_str, '%d/%m/%Y') as date) as fecha_entrega,

        -- Booleans: TRUE/FALSE strings a boolean
        case
            when upper(trim(pago_completado_str)) = 'TRUE' then true
            when upper(trim(pago_completado_str)) = 'FALSE' then false
            else null
        end as pago_completado,

        case
            when upper(trim(entregado_str)) = 'TRUE' then true
            when upper(trim(entregado_str)) = 'FALSE' then false
            else null
        end as entregado,

        -- Pedido_id surrogate
        md5(concat_ws('|', cliente_raw, pedido_string, fecha_emision_str)) as pedido_id

    from renombrado

)

select * from tipado