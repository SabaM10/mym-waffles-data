-- ============================================================
-- dim_cliente: dimensión de clientes.
-- ============================================================
-- Combina la normalización automática de nombres (int_clientes_normalizados)
-- con el mapping manual (seed client_name_mapping) para producir una
-- fila por cada cliente canónico único.
--
-- Los nombres que no tienen mapping quedan marcados como 'Desconocido'
-- para revisión manual.
-- ============================================================

with normalizados as (

    select distinct nombre_normalizado
    from {{ ref('int_clientes_normalizados') }}

),

mapping as (

    select * from {{ ref('client_name_mapping') }}

),

joined as (

    select
        n.nombre_normalizado,
        m.cliente_canonico,
        m.tipo_cliente,
        m.es_ambiguo
    from normalizados n
    left join mapping m
        on n.nombre_normalizado = m.nombre_normalizado

),

con_defaults as (

    select
        nombre_normalizado,
        coalesce(cliente_canonico, 'Desconocido: ' || nombre_normalizado) as cliente_canonico,
        coalesce(tipo_cliente, 'Desconocido') as tipo_cliente,
        coalesce(es_ambiguo, false) as es_ambiguo,
        case
            when cliente_canonico is null then true
            else false
        end as necesita_mapping
    from joined

),

dim_cliente as (

    select
        -- Surrogate key: hash del canónico
        md5(cliente_canonico) as cliente_id,

        cliente_canonico,
        tipo_cliente,
        es_ambiguo,
        necesita_mapping,

        -- Metadata
        current_timestamp as created_at

    from con_defaults
    group by
        cliente_canonico,
        tipo_cliente,
        es_ambiguo,
        necesita_mapping

)

select * from dim_cliente
order by cliente_canonico