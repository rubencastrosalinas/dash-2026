/**
 * dash-2026 · Extractor de Google Ads
 * --------------------------------------------------------------
 * Corre DENTRO de la cuenta de Google Ads (Herramientas > Scripts),
 * asi que no necesita developer token ni aprobacion de la API.
 *
 * Deja el rendimiento diario por campana en una Google Sheet, que
 * despues lee el workflow de GitHub (scripts/fetch_google.py).
 *
 * Primera corrida: dejar SHEET_URL vacio. El script crea la hoja,
 * la deja visible por enlace y escribe la URL en el log. Esa URL se
 * pega aca abajo y en el secret GOOGLE_SHEET_URL del repo.
 */

var SHEET_URL = '';                 // se completa tras la primera corrida
var DESDE     = '2026-01-01';       // inicio del historico
var PESTANA   = 'datos';

function main() {
  var hoy = Utilities.formatDate(new Date(), AdsApp.currentAccount().getTimeZone(), 'yyyy-MM-dd');

  var query =
    'SELECT segments.date, campaign.id, campaign.name, ' +
    'metrics.cost_micros, metrics.impressions, metrics.clicks, ' +
    'metrics.conversions, metrics.conversions_value ' +
    'FROM campaign ' +
    "WHERE segments.date BETWEEN '" + DESDE + "' AND '" + hoy + "'";

  var filas = [['fecha', 'campaign_id', 'campana', 'gasto', 'impresiones', 'clics', 'conversiones', 'valor']];
  var it = AdsApp.report(query).rows();

  while (it.hasNext()) {
    var r = it.next();
    var gasto = Math.round(Number(r['metrics.cost_micros'] || 0) / 1000000);
    var impr  = Number(r['metrics.impressions'] || 0);
    var clics = Number(r['metrics.clicks'] || 0);
    var conv  = Number(r['metrics.conversions'] || 0);
    var valor = Number(r['metrics.conversions_value'] || 0);

    // Se descartan los dias sin actividad para no inflar la hoja.
    if (!gasto && !impr && !clics && !conv && !valor) continue;

    filas.push([
      r['segments.date'],
      String(r['campaign.id']),
      r['campaign.name'],
      gasto,
      impr,
      clics,
      Math.round(conv * 100) / 100,
      Math.round(valor)
    ]);
  }

  if (filas.length < 2) {
    Logger.log('Google Ads no devolvio filas con actividad. No se toca la hoja.');
    return;
  }

  var ss = abrirOCrearHoja();
  var hoja = ss.getSheetByName(PESTANA) || ss.insertSheet(PESTANA);
  hoja.clear();
  hoja.getRange(1, 1, filas.length, filas[0].length).setValues(filas);

  // Sello de la ultima corrida, util para detectar si el script se cayo.
  var sello = ss.getSheetByName('meta') || ss.insertSheet('meta');
  sello.clear();
  sello.getRange(1, 1, 2, 2).setValues([
    ['ultima_corrida', Utilities.formatDate(new Date(), 'UTC', 'yyyy-MM-dd HH:mm') + ' UTC'],
    ['filas', filas.length - 1]
  ]);

  Logger.log('Listo: ' + (filas.length - 1) + ' filas hasta ' + hoy);
  Logger.log('Hoja: ' + ss.getUrl());
}

function abrirOCrearHoja() {
  if (SHEET_URL) return SpreadsheetApp.openByUrl(SHEET_URL);

  var ss = SpreadsheetApp.create('dash-2026 · Google Ads');
  try {
    DriveApp.getFileById(ss.getId())
            .setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  } catch (e) {
    Logger.log('No se pudo abrir el acceso por enlace automaticamente: ' + e);
  }
  Logger.log('>>> HOJA CREADA. Pega esta URL en SHEET_URL: ' + ss.getUrl());
  return ss;
}
