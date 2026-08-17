-- ============================================================
-- dim_fecha: dimensión de calendario.
-- ============================================================
-- Una fila por cada día entre 2024-01-01 y 2027-12-31.
-- Autogenerada con generate_series, no depende de fuentes externas.
-- Nombres de mes y día en español.
-- ============================================================

with calendario as (

    select
        unnest(generate_series(
            '2024-01-01'::date,
            '2027-12-31'::date,
            interval 1 day
        )) as fecha_ts

),

fecha_base as (

    select
        cast(fecha_ts as date) as fecha
    from calendario

),

dim_fecha as (

    select
        -- Surrogate key: YYYYMMDD como INTEGER (fecha_id ordenable naturalmente)
        cast(strftime(fecha, '%Y%m%d') as integer) as fecha_id,

        fecha,

        -- Componentes numéricos
        extract(year from fecha) as año,
        extract(month from fecha) as mes_numero,
        extract(day from fecha) as dia,
        extract(dow from fecha) as dia_semana_numero,
        extract(quarter from fecha) as trimestre,
        extract(week from fecha) as semana_del_año,

        -- Nombre del mes en español
        case extract(month from fecha)
            when 1 then 'enero'
            when 2 then 'febrero'
            when 3 then 'marzo'
            when 4 then 'abril'
            when 5 then 'mayo'
            when 6 then 'junio'
            when 7 then 'julio'
            when 8 then 'agosto'
            when 9 then 'septiembre'
            when 10 then 'octubre'
            when 11 then 'noviembre'
            when 12 then 'diciembre'
        end as nombre_mes,

        -- Nombre del día en español (DuckDB devuelve 0=domingo, 1=lunes...)
        case extract(dow from fecha)
            when 0 then 'domingo'
            when 1 then 'lunes'
            when 2 then 'martes'
            when 3 then 'miércoles'
            when 4 then 'jueves'
            when 5 then 'viernes'
            when 6 then 'sábado'
        end as nombre_dia,

        -- Boolean de fin de semana
        case extract(dow from fecha)
            when 0 then true   -- domingo
            when 6 then true   -- sábado
            else false
        end as es_finde_semana,

        -- Metadata
        current_timestamp as created_at

    from fecha_base

)

select * from dim_fecha
order by fecha