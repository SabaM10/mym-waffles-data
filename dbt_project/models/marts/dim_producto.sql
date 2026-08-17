-- ============================================================
-- dim_producto: dimensión de productos.
-- ============================================================
-- Una fila por SKU válido del catálogo.
-- Fuente: seed productos_catalogo.csv.
-- ============================================================

with catalogo as (

    select * from {{ ref('productos_catalogo') }}

),

producto as (

    select
        -- Surrogate key: hash de masa + sabor
        md5(concat_ws('|', masa, sabor)) as producto_id,

        masa,
        sabor,

        -- Nombre completo para display
        concat(masa, ' ', sabor) as nombre_producto,

        -- Boolean de si está activo
        activo,

        -- Metadata
        current_timestamp as created_at

    from catalogo

)

select * from producto