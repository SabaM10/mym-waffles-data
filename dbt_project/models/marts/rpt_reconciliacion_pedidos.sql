-- ============================================================
-- rpt_reconciliacion_pedidos: mart de auditoría de reconciliación.
-- ============================================================
-- Una fila por pedido, comparando el precio cargado en el sheet
-- contra el precio calculado por el pipeline (matching con dim_tarifa).
--
-- Propósito: exponer discrepancias como señal de calidad de datos.
-- MyM Waffles nunca cobra por debajo de lista, entonces cualquier
-- diferencia es error de carga, bug de matching, o data no modelada.
-- Ver ADR semana 8, Decisión 1.
-- ============================================================

with items_agregados as (

    -- Agrega los items de cada pedido para poder comparar contra
    -- el total del sheet. Cuenta items sin tarifa para señalar
    -- pedidos que tienen algún producto no modelado (ej. proteicos).

    select
        pedido_id,
        sum(precio_item_ars) as precio_calculado_ars,
        count(*) as items_totales,
        sum(case when tarifa_id is null then 1 else 0 end) as items_sin_tarifa

    from {{ ref('fact_pedido_items') }}
    group by pedido_id

),

pedidos_enriquecidos as (

    -- Une la cabecera del pedido con el precio calculado y con los
    -- datos del cliente. Calcula diferencia absoluta y porcentual.

    select
        fp.pedido_id,
        fp.fecha_emision,
        fp.cliente_id,
        c.cliente_canonico,
        c.tipo_cliente,
        fp.cantidad_total,

        fp.precio_total_ars as precio_sheet_ars,
        ia.precio_calculado_ars,
        ia.precio_calculado_ars - fp.precio_total_ars as diferencia_ars,
        round(
            100.0 * (ia.precio_calculado_ars - fp.precio_total_ars)
            / nullif(fp.precio_total_ars, 0),
            2
        ) as diferencia_pct,

        ia.items_totales,
        ia.items_sin_tarifa

    from {{ ref('fact_pedidos') }} fp
    left join items_agregados ia using (pedido_id)
    left join {{ ref('dim_cliente') }} c on fp.cliente_id = c.cliente_id

),

con_categoria as (

    -- Categoriza cada pedido según la magnitud de la discrepancia.
    -- SIN_TARIFA_MODELADA tiene precedencia sobre las demás porque
    -- si falta modelar algún item, el precio_calculado es incompleto
    -- por diseño y cualquier comparación es engañosa.

    select
        *,
        case
            when items_sin_tarifa > 0
                then 'SIN_TARIFA_MODELADA'
            when abs(diferencia_ars) < {{ var('umbral_coincide_ars') }}
                then 'COINCIDE'
            when abs(diferencia_ars) between {{ var('umbral_coincide_ars') }} and {{ var('umbral_discrepancia_grande_ars') }}
                then 'DISCREPANCIA_CHICA'
            else 'DISCREPANCIA_GRANDE'
        end as tipo_discrepancia

    from pedidos_enriquecidos

)

select
    pedido_id,
    fecha_emision,
    cliente_id,
    cliente_canonico,
    tipo_cliente,
    cantidad_total,
    precio_sheet_ars,
    precio_calculado_ars,
    diferencia_ars,
    diferencia_pct,
    items_totales,
    items_sin_tarifa,
    tipo_discrepancia

from con_categoria
order by
    case tipo_discrepancia
        when 'DISCREPANCIA_GRANDE' then 1
        when 'DISCREPANCIA_CHICA' then 2
        when 'SIN_TARIFA_MODELADA' then 3
        when 'COINCIDE' then 4
    end,
    abs(diferencia_ars) desc nulls last