#!/usr/bin/env python3
"""Lee la hoja que alimenta el script de Google Ads y regenera
google-data.js y google-daily.js con la misma forma que los de Meta.
Se ejecuta en GitHub Actions. No requiere dependencias externas."""

import collections
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# La hoja la publica el script "dash-2026 - Extractor diario" dentro de la
# cuenta de Google Ads. Esta compartida por enlace, asi que la URL no es un
# secreto; se puede sobrescribir con GOOGLE_SHEET_URL si algun dia cambia.
HOJA_POR_DEFECTO = ("https://docs.google.com/spreadsheets/d/"
                    "1Ei4xXgxmomxeYj8v7GrGCBlN5lAwo7AAoP0gMpjHJW8/edit")
SHEET = os.environ.get("GOOGLE_SHEET_URL", "").strip() or HOJA_POR_DEFECTO
START = os.environ.get("GOOGLE_START", "2026-06-30").strip()
PESTANA = os.environ.get("GOOGLE_SHEET_TAB", "datos").strip()
WEEK0 = datetime.date(2026, 1, 1)   # mismo ancla semanal que Meta

if not SHEET:
    # Todavia no se configuro la hoja de Google. No es un error: se avisa y se
    # sale limpio para que la actualizacion de Meta siga corriendo igual.
    print("GOOGLE_SHEET_URL sin definir: se omite Google Ads en esta corrida.")
    sys.exit(0)


def id_de_hoja(url):
    partes = url.split("/d/")
    if len(partes) < 2:
        sys.exit("GOOGLE_SHEET_URL no parece una URL de Google Sheets")
    return partes[1].split("/")[0]


def bajar_csv():
    url = ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s"
           % (id_de_hoja(SHEET), urllib.parse.quote(PESTANA)))
    for intento in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and intento < 3:
                time.sleep(15 * (intento + 1))
                continue
            sys.exit("La hoja respondio %s. Revisa que este compartida por enlace." % e.code)
        except urllib.error.URLError as e:
            if intento < 3:
                time.sleep(10)
                continue
            sys.exit("Red: %s" % e)


def parsear(texto):
    import csv
    import io
    lector = csv.DictReader(io.StringIO(texto))
    filas = []
    for f in lector:
        try:
            fecha = datetime.date.fromisoformat((f.get("fecha") or "").strip()[:10])
        except ValueError:
            continue
        cid = (f.get("campaign_id") or "").strip()
        if not cid:
            continue
        filas.append((
            cid,
            (f.get("campana") or cid).strip(),
            fecha,
            int(round(num(f.get("gasto")))),
            int(num(f.get("impresiones"))),
            int(num(f.get("clics"))),
            int(round(num(f.get("valor")))),
            int(round(num(f.get("conversiones")))),
        ))
    return filas


def num(x):
    try:
        return float(str(x or 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def construir(utiles):
    ids = sorted({u[0] for u in utiles})
    idx = {cid: i for i, cid in enumerate(ids)}
    nombres = {u[0]: u[1] for u in utiles}
    campaigns = [nombres[c] for c in ids]

    d0 = datetime.date.fromisoformat(START)
    diario = []
    semanal = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    semanas = set()

    for cid, _nom, fecha, gasto, impr, clics, val, conv in utiles:
        ci = idx[cid]
        diario.append([(fecha - d0).days, ci, gasto, impr, clics, val, conv])
        w = (fecha - WEEK0).days // 7
        semanas.add(w)
        a = semanal[(w, ci)]
        a[0] += gasto; a[1] += impr; a[2] += clics; a[3] += val; a[4] += conv

    diario.sort(key=lambda r: (r[0], r[1]))
    orden = sorted(semanas)
    pos = {w: i for i, w in enumerate(orden)}
    weeks = [(WEEK0 + datetime.timedelta(days=7 * w)).isoformat() for w in orden]
    rows = [[pos[w], ci] + semanal[(w, ci)] for (w, ci) in sorted(semanal)]
    return campaigns, weeks, rows, diario


def escribir(campaigns, weeks, rows, diario, hasta):
    sello = "// Generado automaticamente por .github/workflows/actualizar.yml\n"
    sello += "// Ultima corrida: %s UTC | datos hasta %s\n" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        hasta.isoformat())

    with open("google-data.js", "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write("const GOOGLE_DATA=" + json.dumps(
            {"campaigns": campaigns, "weeks": weeks, "rows": rows},
            ensure_ascii=False, separators=(",", ":")) + ";\n")

    with open("google-daily.js", "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write('const GOOGLE_DAILY_START="%s";\n' % START)
        fh.write("const GOOGLE_DAILY=" + json.dumps(diario, separators=(",", ":")) + ";\n")


def main():
    utiles = parsear(bajar_csv())
    if not utiles:
        sys.exit("La hoja venia vacia: no se sobreescribe nada")
    hasta = max(u[2] for u in utiles)
    campaigns, weeks, rows, diario = construir(utiles)
    escribir(campaigns, weeks, rows, diario, hasta)
    print("campanas: %d | semanas: %d | filas semanales: %d | filas diarias: %d | hasta: %s"
          % (len(campaigns), len(weeks), len(rows), len(diario), hasta))


if __name__ == "__main__":
    main()
