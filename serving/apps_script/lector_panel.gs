/**
 * Lector del panel — Apps Script de la planilla "MyM Pipeline".
 *
 * El pipeline (asset serving/publicar_panel) escribe cuatro pestañas en esta
 * planilla; este script las sirve como JSON al panel (SabaM10/waffles, vista
 * "La semana"). Es de SOLO LECTURA: no tiene doPost y no toca ninguna otra
 * planilla. Por eso vive aparte del script de pedidos, con su propia URL.
 *
 * Instalación (una vez):
 *   1. Abrir la planilla "MyM Pipeline" > Extensiones > Apps Script.
 *   2. Pegar este archivo entero.
 *   3. (Opcional) Configuración del proyecto > Propiedades del script:
 *      CLAVE = la misma clave interna del panel. Si está definida, el GET
 *      exige ?key=<CLAVE>. Si no, responde a cualquiera que tenga la URL.
 *   4. Implementar > Nueva implementación > Aplicación web.
 *      Ejecutar como: yo. Quién tiene acceso: cualquier usuario.
 *   5. La URL /exec va en src/config.js del panel (PIPELINE_URL).
 *   Para cambios posteriores: Administrar implementaciones > lápiz >
 *   Nueva versión (no "Nueva implementación": cambia la URL).
 *
 * Contrato: ver ingestion/panel.py (CONTRATO_VERSION) y
 * docs/decisions/semana-13.md.
 */

var PESTANAS = ['meta', 'forecast_total', 'forecast_sku', 'clientes_semana'];

function doGet(e) {
  var respuesta;
  try {
    var clave = PropertiesService.getScriptProperties().getProperty('CLAVE');
    var recibida = e && e.parameter ? e.parameter.key : '';
    if (clave && recibida !== clave) {
      respuesta = { status: 'error', message: 'Clave incorrecta' };
    } else {
      respuesta = armarRespuesta(leerTablas(SpreadsheetApp.getActiveSpreadsheet()));
    }
  } catch (err) {
    respuesta = { status: 'error', message: String(err && err.message || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(respuesta))
    .setMimeType(ContentService.MimeType.JSON);
}

/** { nombre: [[encabezado...], [fila...], ...] } de las pestañas que existan. */
function leerTablas(planilla) {
  var tablas = {};
  PESTANAS.forEach(function (nombre) {
    var hoja = planilla.getSheetByName(nombre);
    if (!hoja || hoja.getLastRow() === 0) return;
    tablas[nombre] = hoja.getDataRange().getValues();
  });
  return tablas;
}

/**
 * Pura (sin servicios de Google): se prueba en node.
 * Si falta `meta`, contesta { status:'success', vacio:true }: el panel
 * muestra "todavía no hay datos del pipeline" en vez de un error.
 */
function armarRespuesta(tablas) {
  var meta = aObjetos(tablas.meta)[0];
  if (!meta) return { status: 'success', vacio: true };
  return {
    status: 'success',
    vacio: false,
    contrato_version: Number(meta.contrato_version),
    generado: meta.generado,
    semana_predicha: meta.semana_predicha,
    forecast_total: aObjetos(tablas.forecast_total)[0] || null,
    forecast_sku: aObjetos(tablas.forecast_sku),
    clientes: aObjetos(tablas.clientes_semana)
  };
}

/** Filas a objetos por encabezado. Las fechas salen como 'aaaa-mm-dd'. */
function aObjetos(valores) {
  if (!valores || valores.length < 2) return [];
  var encabezado = valores[0];
  return valores.slice(1)
    .filter(function (fila) { return fila.some(function (v) { return v !== ''; }); })
    .map(function (fila) {
      var obj = {};
      encabezado.forEach(function (col, i) {
        var v = fila[i];
        if (Object.prototype.toString.call(v) === '[object Date]') {
          v = Utilities.formatDate(v, 'UTC', 'yyyy-MM-dd');
        }
        obj[col] = v === '' ? null : v;
      });
      return obj;
    });
}
