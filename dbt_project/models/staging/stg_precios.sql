-- ============================================================
-- stg_precios: rate card tipada y limpiada desde raw.precios.
-- ============================================================
-- Renombra columnas a snake_case, tipa cantidades/precios/porcentajes,
-- limpia formato de precios (quita '$', '.', ',') y porcentajes ('%').
-- ============================================================

with source as (

    select * from {{ source('raw', 'precios') }}

),

renombrado as (

    select
        -- Strings normalizados
        upper(trim(SEGMENTO)) as segmento,
        trim(PRODUCTO) as producto_desc,
        trim(ALERTA) as alerta,

        -- Numéricos como string (se tipan abajo)
        PACK as unidades_pack_str,
        "PRECIO VENTA ($)" as precio_venta_str,
        "COSTO PACK ($)" as costo_pack_str,
        "MARGEN REAL" as margen_real_str,
        "vs OBJETIVO" as vs_objetivo_str,

        -- Metadata
        ingested_at

    from source

),

tipado as (

    select
        segmento,
        producto_desc,
        alerta,
        ingested_at,

        -- Unidades pack: cast a INTEGER
        try_cast(unidades_pack_str as integer) as unidades_pack,

        -- Precios: quitar '$' y '.', cambiar ',' por '.', cast a DECIMAL
        try_cast(
            replace(replace(replace(precio_venta_str, '$', ''), '.', ''), ',', '.')
            as decimal(12, 2)
        ) as precio_venta_ars,

        try_cast(
            replace(replace(replace(costo_pack_str, '$', ''), '.', ''), ',', '.')
            as decimal(12, 2)
        ) as costo_pack_ars,

        -- Porcentajes: quitar '%', cambiar ',' por '.', cast a DECIMAL
        try_cast(
            replace(replace(margen_real_str, '%', ''), ',', '.')
            as decimal(6, 2)
        ) as margen_real_pct,

        try_cast(
            replace(replace(vs_objetivo_str, '%', ''), ',', '.')
            as decimal(6, 2)
        ) as vs_objetivo_pct,

        -- Tarifa_id surrogate: hash de segmento + producto + pack
        md5(concat_ws('|', segmento, producto_desc, unidades_pack_str)) as tarifa_id

    from renombrado

)

select * from tipado