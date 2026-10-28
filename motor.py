"""Motor de cálculo: traductor de pestañas -> formato largo, KPIs, semáforo, alertas y resumen.

No depende de Streamlit (lo usan app.py y report.py, y se puede probar solo).
Formato largo: fecha | cliente | fuente | elemento | metrica | valor
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PREGUNTAS = ["carga", "capacitacion", "trato_gerente", "horario", "seguir_6_meses"]
ORDEN_KPIS = ["satisfaccion", "tiempo", "incorrectos", "clima", "rotacion", "ventas", "certificados"]
DIARIOS = {"satisfaccion", "tiempo", "incorrectos", "ventas"}
# Metas para abrir sucursales nuevas (las de la slide de expansión)
METAS_APERTURA = {"satisfaccion": (85, True), "tiempo": (9, False), "incorrectos": (8, False), "rotacion": (25, False)}


# ------------------------------------------------------------------ traductor
def parse_fecha(s: pd.Series) -> pd.Series:
    """Acepta 2026-10-27, 27/10/2026 y números de serie de Sheets/Excel."""
    s = pd.Series(s)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    num = pd.to_numeric(s, errors="coerce")
    es_num = num.notna() & (num > 20000)
    out[es_num] = pd.to_datetime("1899-12-30") + pd.to_timedelta(num[es_num], unit="D")
    txt = s[~es_num].astype(str).str.strip()
    iso = txt.str.match(r"^\d{4}-\d{1,2}-\d{1,2}")
    out[txt[iso].index] = pd.to_datetime(txt[iso].str[:10], errors="coerce")
    otros = txt[~iso]
    out[otros.index] = pd.to_datetime(otros, dayfirst=True, errors="coerce")
    return out.dt.normalize()


def _num(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(",", "").str.strip().replace("", np.nan), errors="coerce")


def traducir(tabs: dict, cliente: str) -> tuple[pd.DataFrame, list[str]]:
    """Pestañas del Sheet -> formato largo. Devuelve (df_largo, avisos)."""
    avisos, partes = [], []
    suc = tabs.get("Sucursales", pd.DataFrame())
    kiosco = set(suc.loc[suc.get("kiosco", pd.Series(dtype=str)).astype(str).str.lower().str.startswith("s"), "sucursal"]) \
        if not suc.empty else set()

    def bloque(fechas, elem, fuente, metrica, valores):
        partes.append(pd.DataFrame({"fecha": fechas.values, "cliente": cliente, "fuente": fuente,
                                    "elemento": pd.Series(elem).values, "metrica": metrica,
                                    "valor": pd.Series(valores).values}))

    d = tabs.get("Diario", pd.DataFrame())
    req = ["fecha", "sucursal", "pedidos", "pedidos_rehechos", "tiempo_min", "ventas_mxn", "encuestas", "satisfechos"]
    if d.empty or not set(req).issubset(d.columns):
        avisos.append("La pestaña Diario no existe o le faltan columnas: " + ", ".join(req))
    else:
        # si hay dos renglones del mismo día y sucursal, gana el último (una corrección del gerente)
        d = d.assign(_f=parse_fecha(d["fecha"])).drop_duplicates(["_f", "sucursal"], keep="last")
        f = d["_f"]
        for col, fuente in [("pedidos", "caja"), ("pedidos_rehechos", "caja"), ("ventas_mxn", "caja"),
                            ("encuestas", "encuesta_qr"), ("satisfechos", "encuesta_qr")]:
            bloque(f, d["sucursal"], fuente, col, _num(d[col]))
        bloque(f, d["sucursal"], np.where(d["sucursal"].isin(kiosco), "autoservicio", "caja"),
               "tiempo_min", _num(d["tiempo_min"]))

    rh = tabs.get("RH_mensual", pd.DataFrame())
    if rh.empty or not {"mes", "sucursal", "plantilla", "bajas"}.issubset(rh.columns):
        avisos.append("La pestaña RH_mensual no existe o le faltan columnas: mes, sucursal, plantilla, bajas, certificados")
    else:
        f = parse_fecha(rh["mes"]).dt.to_period("M").dt.to_timestamp()
        bloque(f, rh["sucursal"], "rh", "plantilla", _num(rh["plantilla"]))
        bloque(f, rh["sucursal"], "rh", "bajas", _num(rh["bajas"]))
        if "certificados" in rh.columns:
            bloque(f, rh["sucursal"], "academia", "certificados", _num(rh["certificados"]))

    e = tabs.get("Encuesta_equipo", pd.DataFrame())
    if not e.empty and set(PREGUNTAS).issubset(e.columns):
        f = parse_fecha(e["fecha"])
        resp = pd.concat([_num(e[p]) for p in PREGUNTAS], axis=1)
        bloque(f, e["sucursal"], "encuesta_equipo", "clima", resp.mean(axis=1).round(2))
        bloque(f, e["sucursal"], "encuesta_equipo", "piensa_irse", (_num(e["seguir_6_meses"]) <= 5).astype(float))

    if not partes:
        return pd.DataFrame(columns=["fecha", "cliente", "fuente", "elemento", "metrica", "valor"]), avisos
    L = pd.concat(partes, ignore_index=True).dropna(subset=["fecha", "valor"])
    return L, avisos


# ------------------------------------------------------------------ cálculos
def pivote_diario(L: pd.DataFrame) -> pd.DataFrame:
    d = L[L["metrica"].isin(["pedidos", "pedidos_rehechos", "ventas_mxn", "encuestas", "satisfechos", "tiempo_min"])]
    p = d.pivot_table(index=["fecha", "elemento"], columns="metrica", values="valor", aggfunc="sum").reset_index()
    for c in ["pedidos", "pedidos_rehechos", "ventas_mxn", "encuestas", "satisfechos", "tiempo_min"]:
        if c not in p:
            p[c] = np.nan
    p["tiempo_x_ped"] = p["tiempo_min"] * p["pedidos"]
    return p


def _ratios(g: pd.DataFrame) -> dict:
    ped = g["pedidos"].sum()
    enc = g["encuestas"].sum()
    return {"satisfaccion": g["satisfechos"].sum() / enc * 100 if enc else np.nan,
            "tiempo": g["tiempo_x_ped"].sum() / ped if ped else np.nan,
            "incorrectos": g["pedidos_rehechos"].sum() / ped * 100 if ped else np.nan}


def ultima_fecha(L: pd.DataFrame):
    d = L[L["metrica"] == "pedidos"]
    return d["fecha"].max() if not d.empty else None


def kpis(L: pd.DataFrame, D: pd.DataFrame, sucs: list, hasta: pd.Timestamp, dias: int) -> dict:
    """Valores de los 7 KPIs para la ventana de `dias` que termina en `hasta`."""
    a = hasta - pd.Timedelta(days=dias - 1)
    g = D[D["elemento"].isin(sucs) & D["fecha"].between(a, hasta)]
    out = _ratios(g)
    ly = D[D["elemento"].isin(sucs) & D["fecha"].between(a - pd.Timedelta(days=364), hasta - pd.Timedelta(days=364))]
    v_ly = ly["ventas_mxn"].sum()
    out["ventas"] = (g["ventas_mxn"].sum() / v_ly - 1) * 100 if v_ly else np.nan
    out["ventas_mxn"] = g["ventas_mxn"].sum()
    out["pedidos"] = g["pedidos"].sum()
    out.update(kpis_mensuales(L, sucs, hasta.to_period("M").to_timestamp()))
    return out


def kpis_mensuales(L: pd.DataFrame, sucs: list, mes: pd.Timestamp) -> dict:
    M = L[L["elemento"].isin(sucs)]
    mes_de = M["fecha"].dt.to_period("M").dt.to_timestamp()
    out = {}
    cl = M[(M["metrica"] == "clima") & (mes_de == mes)]
    out["clima"] = cl["valor"].mean() if not cl.empty else np.nan
    pi = M[(M["metrica"] == "piensa_irse") & (mes_de == mes)]
    out["piensa_irse"] = pi["valor"].mean() * 100 if not pi.empty else np.nan
    pl = M[(M["metrica"] == "plantilla") & (mes_de == mes)]["valor"].sum()
    ce = M[(M["metrica"] == "certificados") & (mes_de == mes)]
    out["certificados"] = ce["valor"].sum() / pl * 100 if pl and not ce.empty else np.nan
    seis = [mes - pd.DateOffset(months=k) for k in range(6)]   # renuncias de los últimos 6 meses, anualizadas
    b = M[(M["metrica"] == "bajas") & (mes_de.isin(seis))]["valor"].sum()
    p6 = M[(M["metrica"] == "plantilla") & (mes_de.isin(seis))]
    p6m = p6.groupby(p6["fecha"].dt.to_period("M"))["valor"].sum().mean() if not p6.empty else 0
    out["rotacion"] = b / p6m * 2 * 100 if p6m else np.nan
    return out


def comparar(L, D, sucs, hasta, dias):
    """(actual, anterior). Los diarios comparan contra la ventana anterior; los mensuales contra el mes anterior."""
    cur = kpis(L, D, sucs, hasta, dias)
    prev = kpis(L, D, sucs, hasta - pd.Timedelta(days=dias), dias)
    mes_ant = (hasta.to_period("M") - 1).to_timestamp()
    prev.update(kpis_mensuales(L, sucs, mes_ant))
    return cur, prev


def estado(kpi: str, valor: float, cfg: dict) -> tuple[str, str]:
    """('verde'|'amarillo'|'rojo'|'gris', texto)."""
    if valor is None or pd.isna(valor):
        return "gris", "Sin datos"
    meta, ini, mas = cfg["meta"], cfg["inicio"], cfg["mas_es_mejor"]
    cumple = valor >= meta if mas else valor <= meta
    if cumple:
        return "verde", "En meta"
    if kpi == "ventas":
        return ("amarillo", "Cerca") if valor >= meta - 2 else ("rojo", "Atrasado")
    avance = (valor - ini) / (meta - ini) if meta != ini else 0
    return ("amarillo", "En camino") if avance >= 0.5 else ("rojo", "Atrasado")


def fmt(kpi: str, v, cfg: dict) -> str:
    if v is None or pd.isna(v):
        return "—"
    if kpi == "clima":
        return f"{v:.1f}/10"
    if kpi == "tiempo":
        return f"{v:.1f} min"
    if kpi == "ventas":
        return f"{v:+.1f}%"
    return f"{v:.0f}%"


def serie(L, D, kpi: str, sucs: list, desde=None) -> pd.DataFrame:
    """Serie semanal (KPIs diarios) o mensual (los demás): columnas periodo, valor."""
    if kpi in DIARIOS:
        g = D[D["elemento"].isin(sucs)].copy()
        g["periodo"] = g["fecha"].dt.to_period("W-SUN").dt.start_time
        w = g.groupby("periodo")[["pedidos", "pedidos_rehechos", "encuestas", "satisfechos", "tiempo_x_ped", "ventas_mxn"]].sum()
        dias_sem = g.groupby("periodo")["fecha"].nunique()
        w = w[dias_sem >= 4]
        if kpi == "satisfaccion":
            v = w["satisfechos"] / w["encuestas"] * 100
        elif kpi == "tiempo":
            v = w["tiempo_x_ped"] / w["pedidos"]
        elif kpi == "incorrectos":
            v = w["pedidos_rehechos"] / w["pedidos"] * 100
        else:
            ant = w["ventas_mxn"].shift(52)
            v = (w["ventas_mxn"] / ant - 1) * 100
        s = v.dropna().rename("valor").reset_index()
    else:
        meses = sorted(L["fecha"].dt.to_period("M").dt.to_timestamp().unique())
        if kpi == "rotacion":
            meses = meses[5:]   # la rotación usa 6 meses de historia
        filas = [(m, kpis_mensuales(L, sucs, m)[kpi]) for m in meses]
        s = pd.DataFrame(filas, columns=["periodo", "valor"]).dropna()
    if desde is not None:
        s = s[s["periodo"] >= desde]
    return s


def tabla_sucursales(L, D, sucursales, hasta, dias, cfg_kpis) -> pd.DataFrame:
    filas = []
    for s in sucursales:
        k = kpis(L, D, [s], hasta, dias)
        fila = {"Sucursal": s}
        rojos = 0
        for kp in ORDEN_KPIS:
            fila[kp] = k[kp]
            e, _ = estado(kp, k[kp], cfg_kpis[kp])
            rojos += e == "rojo"
            fila[f"_e_{kp}"] = e
        fila["en_meta"] = sum(fila[f"_e_{kp}"] == "verde" for kp in ORDEN_KPIS)
        fila["rojos"] = rojos
        fila["puntaje"] = fila["en_meta"] - rojos
        fila["piensa_irse"] = k["piensa_irse"]
        filas.append(fila)
    return pd.DataFrame(filas).sort_values(["puntaje", "en_meta"], ascending=[False, False], ignore_index=True)


# ------------------------------------------------------------------ alertas
def nivel(prio: float) -> str:
    return "🔴" if prio >= 70 else ("🟠" if prio >= 40 else "🟢")


def alertas(L, D, marca, hasta, dias) -> list[tuple]:
    """[(prioridad, emoji, título, texto)] ordenadas de mayor a menor prioridad."""
    cfg = marca["kpis"]
    sucs = marca["sucursales"]
    piloto = [s for s in marca.get("piloto_kioscos", []) if s in sucs]
    per = "la última semana" if dias == 7 else "las últimas 4 semanas"
    out = []
    mes = hasta.to_period("M").to_timestamp()
    mes_ant = (hasta.to_period("M") - 1).to_timestamp()
    T = tabla_sucursales(L, D, sucs, hasta, dias, cfg)

    for s in sucs:   # 1. clima laboral: aviso antes de que alguien renuncie
        a, b = kpis_mensuales(L, [s], mes_ant), kpis_mensuales(L, [s], mes)
        if pd.notna(b["clima"]) and pd.notna(a["clima"]) and (b["clima"] < 6.3 or a["clima"] - b["clima"] >= 0.6):
            irse = f" y {b['piensa_irse']:.0f}% del equipo dice que podría irse en 6 meses" if pd.notna(b["piensa_irse"]) else ""
            que = (f"El clima laboral bajó de {a['clima']:.1f} a {b['clima']:.1f}/10" if a["clima"] - b["clima"] >= 0.3
                   else f"El clima laboral está en {b['clima']:.1f}/10, muy por debajo de la meta de 8")
            out.append((85 + min(10, (a["clima"] - b["clima"]) * 5), f"Riesgo de renuncias en {s}",
                        f"{que}{irse}. "
                        "Que el gerente de zona platique con el equipo esta semana, antes de que alguien renuncie."))

    for _, r in T[T["rojos"] >= 3].iterrows():   # 2. sucursales atrasadas
        lista = ", ".join(cfg[k]["nombre"].lower() for k in ORDEN_KPIS if r[f"_e_{k}"] == "rojo")
        out.append((72 + r["rojos"], f"{r['Sucursal']} va atrasada",
                    f"Está lejos de la meta en {int(r['rojos'])} de 7 indicadores ({lista}). "
                    "Conviene mandar a un entrenador de la academia dos semanas y revisar el refuerzo en hora pico."))

    for s in sucs:   # 3. errores que suben
        c1 = _ratios(D[(D["elemento"] == s) & D["fecha"].between(hasta - pd.Timedelta(days=6), hasta)])["incorrectos"]
        c0 = _ratios(D[(D["elemento"] == s) & D["fecha"].between(hasta - pd.Timedelta(days=13), hasta - pd.Timedelta(days=7))])["incorrectos"]
        if pd.notna(c1) and pd.notna(c0) and c1 - c0 >= 2:
            out.append((55 + min(15, (c1 - c0) * 2), f"Suben los pedidos incorrectos en {s}",
                        f"Pasaron de {c0:.1f}% a {c1:.1f}% en una semana. Revisar si entró personal nuevo sin certificar."))

    if piloto and len(piloto) < len(sucs):   # 4. ¿funcionan los kioscos?
        a = hasta - pd.Timedelta(days=dias - 1)
        g = D[D["fecha"].between(a, hasta)]
        tk = _ratios(g[g["elemento"].isin(piloto)])["tiempo"]
        tn = _ratios(g[~g["elemento"].isin(piloto)])["tiempo"]
        if pd.notna(tk) and pd.notna(tn) and tn - tk >= 0.8:
            sin = g[~g["elemento"].isin(piloto)].groupby("elemento").agg(ped=("pedidos", "sum"), t=("tiempo_x_ped", "sum"))
            sin["t"] = sin["t"] / sin["ped"]
            sig = (sin["ped"].rank() + sin["t"].rank()).idxmax()
            out.append((45, "Los kioscos están funcionando",
                        f"Las sucursales con kiosco atienden en {tk:.1f} min y las demás en {tn:.1f} min. "
                        f"Si se libera presupuesto, la siguiente candidata para kiosco es {sig} (muchos pedidos y fila larga)."))

    cert_bajo = [r["Sucursal"] for _, r in T.iterrows() if pd.notna(r["certificados"]) and r["certificados"] < 50]
    if cert_bajo:   # 5. certificación
        out.append((50, "Certificación atrasada",
                    f"{', '.join(cert_bajo)} {'tiene' if len(cert_bajo) == 1 else 'tienen'} menos de la mitad del equipo certificado. "
                    "Sin certificación los errores tardan más en bajar."))

    k = kpis(L, D, sucs, hasta, dias)   # 6. ventas
    if pd.notna(k["ventas"]):
        if k["ventas"] < cfg["ventas"]["meta"]:
            out.append((80, "Ventas por debajo del mínimo",
                        f"Las ventas crecen {k['ventas']:.1f}% contra el año anterior; el mínimo es {cfg['ventas']['meta']}%."))
        else:
            out.append((15, "Ventas protegidas",
                        f"Las ventas crecen {k['ventas']:.1f}% contra el mismo periodo del año pasado (mínimo {cfg['ventas']['meta']}%)."))
    if pd.notna(k["satisfaccion"]):   # 7. satisfacción general
        falta = cfg["satisfaccion"]["meta"] - k["satisfaccion"]
        if falta > 0:
            out.append((40, "Falta poco en satisfacción",
                        f"En {per}, {k['satisfaccion']:.0f}% de los clientes salió satisfecho; faltan {falta:.0f} puntos para la meta. "
                        "Lo que más la mueve es el tiempo de atención."))
        else:
            out.append((20, "Satisfacción en meta", f"{k['satisfaccion']:.0f}% de los clientes salió satisfecho en {per}."))
    return sorted(out, key=lambda x: -x[0])


def metas_apertura(k: dict) -> list[tuple]:
    """[(nombre_kpi, valor, meta, cumple)] para las 4 metas que deciden la expansión."""
    res = []
    for kp, (meta, mas) in METAS_APERTURA.items():
        v = k.get(kp)
        ok = pd.notna(v) and (v >= meta if mas else v <= meta)
        res.append((kp, v, meta, bool(ok)))
    return res


def resumen(k: dict, kprev: dict, marca: dict, T: pd.DataFrame, dias: int) -> str:
    cfg = marca["kpis"]
    per = "En los últimos 7 días" if dias == 7 else "En las últimas 4 semanas"
    en_meta = sum(estado(kp, k[kp], cfg[kp])[0] == "verde" for kp in ORDEN_KPIS)
    partes = [f"{per}, {marca['cliente']} atendió en **{fmt('tiempo', k['tiempo'], cfg)}** en promedio "
              f"(meta {cfg['tiempo']['meta']} min) y **{k['satisfaccion']:.0f}%** de los clientes salió satisfecho."]
    if pd.notna(kprev.get("tiempo")) and pd.notna(k["tiempo"]):
        dif = k["tiempo"] - kprev["tiempo"]
        if abs(dif) >= 0.1:
            partes.append(f"El tiempo {'bajó' if dif < 0 else 'subió'} {abs(dif):.1f} min frente al periodo anterior.")
    partes.append(f"**{en_meta} de 7** indicadores ya {'está' if en_meta == 1 else 'están'} en meta.")
    if not T.empty:
        peor = T.iloc[-1]
        partes.append(f"La sucursal que más apoyo necesita es **{peor['Sucursal']}**; la que mejor va, **{T.iloc[0]['Sucursal']}**.")
    return " ".join(partes)
