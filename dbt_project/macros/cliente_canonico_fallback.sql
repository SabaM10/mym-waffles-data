{% macro cliente_canonico_fallback(canonico, normalizado) -%}
    coalesce({{ canonico }}, 'Desconocido: ' || {{ normalizado }})
{%- endmacro %}