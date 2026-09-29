#!/usr/bin/env python3
"""Mezcla nuevas filas de Meta en data/meta-history.json y regenera
meta-data.js y meta-daily.js.

Uso:  python scripts/actualizar_meta.py nuevo.json

nuevo.json es la respuesta cruda del conector de Meta Ads: una lista de
objetos con date_start, name, amount_spent, impressions, clicks y, si las
hubo, omni_purchase y omni_purchase_values. Se ignora cualquier campo extra.

Todo el calculo de semanas y de indices vive aqui, no en la sesion.
"""

import datetime
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(RAIZ, "data", "meta-history.json")
WEEK0 = datetime.date(2026, 1, 1)


def num(x):
    if isinstance(x, dict):
        x = x.get("value")
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def leer_nuevas(ruta):
    with open(ruta, encoding="utf-8") as fh:
        crudo = json.load(fh)
    # El conector a veces devuelve la lista dentro de una cadena JSON.
    if isinstance(crudo, str):
        crudo = json.loads(crudo)
    if isinstance(crudo, dict):
        crudo = crudo.get("ad_entities", crudo.get("data", []))
        if isinstance(crudo, str):
            crudo = json.loads(crudo)

    filas, nombres = {}, {}
    for f in crudo:
        fecha = (f.get("date_start") or "").strip()[:10]
        # Se cruza SIEMPRE por id: el nombre de una campana puede cambiar en
        # Meta y cruzar por nombre partiria el historico en dos series.
        cid = str(f.get("id") or f.get("campaign_id") or "").strip()
        nombre = (f.get("name") or f.get("campaign_name") or "").strip()
        if not fecha or not cid:
            continue
        if nombre:
            nombres[cid] = nombre
        gasto = int(round(num(f.get("amount_spent", f.get("spend")))))
        impr = int(num(f.get("impressions")))
        clics = int(num(f.get("clicks")))
        compras = int(round(num(f.get("omni_purchase", f.get("purchases")))))
        valor = int(round(num(f.get("omni_purchase_values", f.get("purchase_value")))))
        if not valor:
            # Si solo vino el ROAS, el valor se deduce del gasto.
            roas = num(f.get("website_purchase_roas") or f.get("purchase_roas"))
            valor = int(round(gasto * roas))
        if not (gasto or impr or clics or valor or compras):
            continue
        filas.setdefault(fecha, {})[cid] = [gasto, impr, clics, valor, compras]
    return filas, nombres


def semana_de(fecha):
    d = datetime.date.fromisoformat(fecha)
    return (WEEK0 + datetime.timedelta(days=7 * ((d - WEEK0).days // 7))).isoformat()


def generar(hist):
    # hist["campanas"] traduce cada id a su nombre para mostrar.
    inicio = hist["inicio_diario"]
    diario = hist["diario"]
    previas = hist["semanas_previas"]

    claves = set()
    for dia in diario.values():
        claves.update(dia)
    for sem in previas.values():
        claves.update(sem)
    orden = sorted(claves, key=lambda k: hist["campanas"].get(k, k))
    campaigns = [hist["campanas"].get(k, k) for k in orden]
    idx = {k: i for i, k in enumerate(orden)}

    # Semanal: las previas tal cual, las posteriores agregadas desde el diario.
    semanal = {}
    for w, campos in previas.items():
        for n, v in campos.items():
            semanal.setdefault(w, {})[n] = list(v)
    for fecha, campos in diario.items():
        w = semana_de(fecha)
        if w < inicio:
            continue   # esa semana ya viene cerrada en las previas
        for n, v in campos.items():
            a = semanal.setdefault(w, {}).setdefault(n, [0, 0, 0, 0, 0])
            for i in range(5):
                a[i] += v[i]

    weeks = sorted(semanal)
    wpos = {w: i for i, w in enumerate(weeks)}
    rows = []
    for w in weeks:
        for n in sorted(semanal[w]):
            v = semanal[w][n]
            rows.append([wpos[w], idx[n], v[0], v[1], v[2], v[3], v[4]])

    d0 = datetime.date.fromisoformat(inicio)
    filas_dia = []
    for fecha in sorted(diario):
        off = (datetime.date.fromisoformat(fecha) - d0).days
        for n in sorted(diario[fecha]):
            v = diario[fecha][n]
            filas_dia.append([off, idx[n], v[0], v[1], v[2], v[3], v[4]])

    return campaigns, weeks, rows, filas_dia, inicio


def escribir(campaigns, weeks, rows, filas_dia, inicio, hasta):
    sello = ("// Generado por scripts/actualizar_meta.py\n"
             "// Ultima corrida: %s UTC | datos hasta %s\n" % (
                 datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 hasta))
    with open(os.path.join(RAIZ, "meta-data.js"), "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write("const DATA=" + json.dumps(
            {"campaigns": campaigns, "weeks": weeks, "rows": rows},
            ensure_ascii=False, separators=(",", ":")) + ";\n")
    with open(os.path.join(RAIZ, "meta-daily.js"), "w", encoding="utf-8") as fh:
        fh.write(sello)
        fh.write('const DAILY_START="%s";\n' % inicio)
        fh.write("const DAILY=" + json.dumps(filas_dia, separators=(",", ":")) + ";\n")


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: actualizar_meta.py nuevo.json")

    with open(HIST, encoding="utf-8") as fh:
        hist = json.load(fh)

    nuevas, nombres = leer_nuevas(sys.argv[1])
    # Un renombre en Meta actualiza la etiqueta sin tocar el historico.
    hist.setdefault("campanas", {}).update(nombres)
    if not nuevas:
        sys.exit("El archivo no traia filas utiles: no se toca nada.")

    # El dia en curso se reescribe cada vez; los cerrados se corrigen si Meta
    # ajusto las cifras. Nunca se borra un dia que ya existia.
    cambios = 0
    for fecha, campos in nuevas.items():
        if hist["diario"].get(fecha) != campos:
            cambios += 1
        hist["diario"][fecha] = campos

    with open(HIST, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False, separators=(",", ":"))

    hasta = max(hist["diario"])
    escribir(*generar(hist), hasta=hasta)
    print("dias recibidos: %d | dias con cambios: %d | historico hasta: %s"
          % (len(nuevas), cambios, hasta))


if __name__ == "__main__":
    main()
