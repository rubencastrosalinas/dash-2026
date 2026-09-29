#!/usr/bin/env python3
"""Descarga el rendimiento diario por campana desde la Marketing API de Meta
y regenera meta-daily.js y meta-data.js para el dashboard.
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

TOKEN = os.environ.get("META_TOKEN", "").strip()
ACCT = os.environ.get("META_AD_ACCOUNT", "372739988524670").strip()
START = os.environ.get("META_START", "2026-01-01").strip()
VER = os.environ.get("META_API_VERSION", "v21.0").strip()
WEEK0 = datetime.date(2026, 1, 1)   # jueves: ancla de las semanas

if not TOKEN:
    sys.exit("Falta el secret META_TOKEN")


def api(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for intento in range(4):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode()[:500]
            if e.code in (429, 500, 502, 503) and intento < 3:
                time.sleep(20 * (intento + 1))
                continue
            sys.exit("Meta API %s: %s" % (e.code, cuerpo))
        except urllib.error.URLError as e:
            if intento < 3:
                time.sleep(15)
                continue
            sys.exit("Red: %s" % e)


def descargar():
    hasta = datetime.date.today()
    url = "https://graph.facebook.com/%s/act_%s/insights" % (VER, ACCT)
    params = {
        "level": "campaign",
        "time_increment": 1,
        "time_range": json.dumps({"since": START, "until": hasta.isoformat()}),
        "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values",
        "limit": 500,
        "access_token": TOKEN,
    }
    filas = []
    pagina = api(url, params)
    while True:
        filas.extend(pagina.get("data", []))
        sig = pagina.get("paging", {}).get("next")
        if not sig:
            break
        pagina = api(sig)
    return filas, hasta


def valor(lista, tipos):
    for t in tipos:
        for a in lista or []:
            if a.get("action_type") == t:
                try:
                    return float(a.get("value") or 0)
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def construir(filas):
    # Primero se normaliza y se descartan los dias sin actividad, para que una
    # campana que no gasto nada no aparezca en el filtro del dashboard.
    utiles = []
    for f in filas:
        gasto = int(round(num(f.get("spend"))))
        impr = int(num(f.get("impressions")))
        clics = int(num(f.get("clicks")))
        val = int(round(valor(f.get("action_values"), ["omni_purchase", "purchase"])))
        comp = int(round(valor(f.get("actions"), ["omni_purchase", "purchase"])))
        if not (gasto or impr or clics or val or comp):
            continue
        utiles.append((f["campaign_id"], f.get("campaign_name") or f["campaign_id"],
                       datetime.date.fromisoformat(f["date_start"]),
                       gasto, impr, clics, val, comp))

    ids = sorted({u[0] for u in utiles})
    idx = {cid: i for i, cid in enumerate(ids)}
    nombres = {}
    for u in utiles:
        nombres[u[0]] = u[1]
    campaigns = [nombres[c] for c in ids]

    d0 = datetime.date.fromisoformat(START)
    diario = []
    semanal = collections.defaultdict(lambda: [0, 0, 0, 0.0, 0])
    semanas = set()

    for cid, _nom, fecha, gasto, impr, clics, val, comp in utiles:
        ci = idx[cid]
        diario.append([(fecha - d0).days, ci, gasto, impr, clics, val, comp])
        w = (fecha - WEEK0).days // 7
        semanas.add(w)
        a = semanal[(w, ci)]
        a[0] += gasto; a[1] += impr; a[2] += clics; a[3] += val; a[4] += comp

    diario.sort(key=lambda r: (r[0], r[1]))
    orden = sorted(semanas)
    pos = {w: i for i, w in enumerate(orden)}
    weeks = [(WEEK0 + datetime.timedelta(days=7 * w)).isoformat() for w in orden]
    rows = []
    for (w, ci) in sorted(semanal):
        a = semanal[(w, ci)]
        rows.append([pos[w], ci, a[0], a[1], a[2], int(round(a[3])), a[4]])
    return campaigns, weeks, rows, diario


def escribir(campaigns, weeks, rows, diario, hasta):
    sello = "// Generado automaticamente por .github/workflows/actualizar-meta.yml\n"
    sello += "// Ultima corrida: %s UTC | datos hasta %s\n" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        hasta.isoformat())

    with open("meta-data.js", "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write("const DATA=" + json.dumps(
            {"campaigns": campaigns, "weeks": weeks, "rows": rows},
            ensure_ascii=False, separators=(",", ":")) + ";\n")

    with open("meta-daily.js", "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write('const DAILY_START="%s";\n' % START)
        fh.write("const DAILY=" + json.dumps(diario, separators=(",", ":")) + ";\n")


def main():
    filas, hasta = descargar()
    if not filas:
        sys.exit("Meta no devolvio filas para el rango pedido")
    campaigns, weeks, rows, diario = construir(filas)
    if not diario or not rows:
        sys.exit("Los datos venian vacios: no se sobreescribe nada")
    escribir(campaigns, weeks, rows, diario, hasta)
    print("campanas: %d | semanas: %d | filas semanales: %d | filas diarias: %d | hasta: %s"
          % (len(campaigns), len(weeks), len(rows), len(diario), hasta))


if __name__ == "__main__":
    main()
