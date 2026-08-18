-- ============================================================
-- int_clientes_normalizados: normalización automática de nombres de cliente.
-- ============================================================
-- Aplica reglas mecánicas al campo cliente_raw de stg_pedidos:
-- - Lowercase.
-- - Trim.
-- - Colapsar espacios múltiples a uno.
-- - Quitar acentos.
--
-- Este modelo NO decide qué clientes existen. Solo normaliza para que
-- después dim_cliente pueda hacer matching con el mapping manual.
-- ============================================================

with source as (

    select cliente_raw from {{ ref('stg_pedidos') }}

),

normalizado as (

    select
        cliente_raw,

        -- Pipeline de normalización:
        -- 1. lower: minúsculas
        -- 2. trim: sacar espacios al inicio/final
        -- 3. regexp_replace: colapsar espacios múltiples a uno solo
        -- 4. strip_accents: quitar acentos (á → a, ñ → n, etc.)
        strip_accents(
            regexp_replace(
                trim(lower(cliente_raw)),
                '\s+', ' ', 'g'
            )
        ) as nombre_normalizado

    from source

),

distinct_normalizado as (

    select distinct
        cliente_raw,
        nombre_normalizado
    from normalizado
    where nombre_normalizado is not null
      and nombre_normalizado != ''

)

select * from distinct_normalizado
order by nombre_normalizado