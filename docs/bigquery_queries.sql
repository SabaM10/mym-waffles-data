-- Consultas de ejemplo sobre los marts exportados a BigQuery (dataset mym_serving).
-- Reemplazar `PROYECTO` por el id del proyecto GCP. Los nombres de cliente estan
-- pseudonimizados (cliente_xxxxxxxx). Columnas con ñ pasan a n: año -> ano.

-- 1) Facturacion semanal con variacion contra la semana anterior (window function).
SELECT
  ano,
  semana_del_ano,
  total_facturado_ars,
  total_facturado_ars - LAG(total_facturado_ars) OVER (ORDER BY ano, semana_del_ano) AS variacion_ars,
  SAFE_DIVIDE(
    total_facturado_ars - LAG(total_facturado_ars) OVER (ORDER BY ano, semana_del_ano),
    LAG(total_facturado_ars) OVER (ORDER BY ano, semana_del_ano)
  ) AS variacion_pct
FROM `PROYECTO.mym_serving.rpt_ventas_semanales`
ORDER BY ano, semana_del_ano;

-- 2) Mix B2B vs B2C del facturado por mes.
SELECT
  ano,
  mes_numero,
  SUM(facturado_b2b_ars) AS b2b_ars,
  SUM(facturado_b2c_ars) AS b2c_ars,
  SAFE_DIVIDE(SUM(facturado_b2b_ars), SUM(total_facturado_ars)) AS share_b2b
FROM `PROYECTO.mym_serving.rpt_ventas_semanales`
GROUP BY ano, mes_numero
ORDER BY ano, mes_numero;

-- 3) Clientes B2B con silencio atipico: mas de 1 desvio sobre su intervalo medio.
SELECT
  cliente_canonico,
  total_pedidos,
  dias_desde_ultimo_pedido,
  intervalo_promedio_dias,
  intervalo_desvio_dias,
  SAFE_DIVIDE(dias_desde_ultimo_pedido - intervalo_promedio_dias, intervalo_desvio_dias) AS z_score
FROM `PROYECTO.mym_serving.mart_b2b_reorder_probabilistico`
WHERE total_pedidos >= 4
  AND dias_desde_ultimo_pedido > intervalo_promedio_dias + intervalo_desvio_dias
ORDER BY z_score DESC;
