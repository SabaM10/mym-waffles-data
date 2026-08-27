# Ideas futuras

## Post-MVP (después de semana 12)

### Colapsar app de carga y pipeline de datos
Cuando el usuario escribe nombre de cliente que autocomplete con el del catálogo canónico. Elimina normalización manual futura.

Flow:
1. dbt exporta dim_cliente como JSON.
2. App lee el JSON y alimenta autocompletado.
3. Al guardar, escribe el canónico, no la variante.

Beneficio: shift-left de calidad de datos.