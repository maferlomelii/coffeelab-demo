"""Datos ficticios de CoffeeLab.

Genera las pestañas del Google Sheet tal como las llenaría la operación real:
  - Diario:          fecha | sucursal | pedidos | pedidos_rehechos | tiempo_min | ventas_mxn | encuestas | satisfechos
                     (caja + autoservicio + encuesta QR del ticket, un renglón por sucursal por día)
  - RH_mensual:      mes | sucursal | plantilla | bajas | certificados
                     (RH + academia, un renglón por sucursal por mes)
  - Encuesta_equipo: fecha | sucursal | carga | capacitacion | trato_gerente | horario | seguir_6_meses
                     (una respuesta anónima por renglón, escala 1 a 10)
  - Sucursales:      sucursal | kiosco

Se usa para: 1) crear el Excel que se sube a Google Sheets, 2) el modo demo sin Sheet,
3) el botón "Simular cierre del día" de la app.

La historia: antes del plan, 12 min, 18% de errores, 72% de satisfacción, 35% de rotación.
Desde el inicio del plan cada sucursal mejora a su ritmo; las 5 con kiosco, más rápido.
Dos sucursales van atrasadas y en una el clima laboral empezó a caer (para que salgan alertas).
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

DIAS_HISTORIA = 500  # alcanza para comparar ventas contra el mismo periodo del año anterior
RITMO = {"Lindavista": 0.35, "Insurgentes Sur": 0.45, "Narvarte": 0.9, "Tlalpan": 0.75,
         "Juárez": 1.1, "Condesa": 1.2, "Coyoacán": 1.05, "San Ángel": 1.15}
CLIMA_EN_CAIDA = "Narvarte"
PREGUNTAS = ["carga", "capacitacion", "trato_gerente", "horario", "seguir_6_meses"]


def _rampa(dias, tau):
    d = np.maximum(np.asarray(dias, dtype=float), 0)
    return 1 - np.exp(-d / tau)


class _Suc:
    """Parámetros fijos de una sucursal (siempre los mismos para el mismo nombre)."""

    def __init__(self, nombre: str, es_piloto: bool):
        rng = np.random.default_rng(sum(map(ord, nombre)) * 7919)
        self.r = RITMO.get(nombre, 1.0)
        self.piloto = es_piloto
        self.base = rng.uniform(280, 520) * (1.15 if es_piloto else 1.0)
        self.ticket = rng.uniform(78, 96)
        self.t_ini = 12 + rng.normal(0, 0.5)
        self.t_fin = (7.5 if es_piloto else 9.2) + (1 - min(self.r, 1.0)) * 2.2
        self.e_ini = 18 + rng.normal(0, 1.0)
        self.e_fin = (4.2 if es_piloto else 7.5) + (1 - min(self.r, 1.0)) * 6
        self.resp = rng.uniform(0.05, 0.08)
        self.plantilla = float(np.round(rng.uniform(16, 22)))


def diario(fechas, suc: str, p: _Suc, inicio_plan, rng) -> pd.DataFrame:
    fechas = pd.DatetimeIndex(fechas)
    n = len(fechas)
    dias = (fechas - pd.Timestamp(inicio_plan)).days.to_numpy()
    edad = (fechas - pd.Timestamp("2024-01-01")).days.to_numpy()
    p_ops = _rampa(dias, 55 / p.r)
    pedidos = np.round(p.base * 1.15 ** (edad / 365) * np.where(fechas.dayofweek >= 5, 0.82, 1.0)
                       * (1 + 0.03 * p_ops) * rng.normal(1, 0.06, n) / 1.15 ** 2)
    ventas = np.round(pedidos * p.ticket * rng.normal(1, 0.03, n))
    tiempo = p.t_ini - (p.t_ini - p.t_fin) * p_ops + rng.normal(0, 0.45, n)
    err = np.clip(p.e_ini - (p.e_ini - p.e_fin) * _rampa(dias, 45 / p.r) + rng.normal(0, 1.1, n), 1, 40)
    sat = np.clip(72 + (12 - tiempo) * 2.6 + (18 - err) * 0.72 + rng.normal(0, 2.2, n), 40, 99)
    enc = np.round(pedidos * p.resp)
    return pd.DataFrame({
        "fecha": fechas.strftime("%Y-%m-%d"), "sucursal": suc,
        "pedidos": pedidos.astype(int), "pedidos_rehechos": np.round(pedidos * err / 100).astype(int),
        "tiempo_min": np.round(tiempo, 1), "ventas_mxn": ventas.astype(int),
        "encuestas": enc.astype(int), "satisfechos": np.round(enc * sat / 100).astype(int),
    })


def generar(marca: dict, hoy: date | None = None, semilla: int = 7) -> dict:
    """Devuelve {"Diario": df, "RH_mensual": df, "Encuesta_equipo": df, "Sucursales": df}."""
    hoy = hoy or date.today()
    rng = np.random.default_rng(semilla)
    piloto = set(marca.get("piloto_kioscos", []))
    inicio_plan = pd.Timestamp(hoy - timedelta(days=int(marca.get("dias_desde_inicio_plan", 120))))
    fechas = pd.date_range(hoy - timedelta(days=DIAS_HISTORIA - 1), hoy, freq="D")
    meses = pd.date_range(fechas[0].to_period("M").to_timestamp(),
                          pd.Timestamp(hoy).to_period("M").to_timestamp(), freq="MS")
    d_list, rh_list, enc_list = [], [], []
    for suc in marca["sucursales"]:
        p = _Suc(suc, suc in piloto)
        d_list.append(diario(fechas, suc, p, inicio_plan, rng))

        d_mes = (meses + pd.Timedelta(days=14) - inicio_plan).days.to_numpy()
        rot = 0.35 - (0.35 - (0.19 + (1 - min(p.r, 1.0)) * 0.12)) * _rampa(d_mes, 80 / p.r)
        acum = np.cumsum(p.plantilla * rot / 12) + rng.uniform(0, 1)   # renuncias acumuladas esperadas
        bajas = np.diff(np.floor(acum), prepend=np.floor(acum[0] - p.plantilla * rot[0] / 12))
        cert = np.clip(np.maximum(d_mes, 0) / 150 * 100 * min(p.r * 1.05, 1.0), 0, 100)
        rh = pd.DataFrame({"mes": meses.strftime("%Y-%m-%d"), "sucursal": suc,
                           "plantilla": int(p.plantilla), "bajas": bajas.astype(int),
                           "certificados": np.round(p.plantilla * cert / 100).astype(int)})
        rh["certificados"] = rh["certificados"].astype(object)
        rh.loc[d_mes < 0, "certificados"] = ""   # antes del plan no se medía
        rh_list.append(rh)

        clima = (6.1 - 0.3 * (1 - min(p.r, 1.0))
                 + 2.2 * _rampa(d_mes, 70 / p.r) * min(p.r, 1.0))
        if suc == CLIMA_EN_CAIDA:
            clima[-2:] = [clima[-3] - 0.7, clima[-3] - 1.5]
        for m, d, c in zip(meses, d_mes, clima):
            if d < 0:
                continue
            fin_mes = min(m + pd.offsets.MonthEnd(0), pd.Timestamp(hoy))
            n = int(p.plantilla * rng.uniform(0.6, 0.9))
            dias_r = rng.integers(0, max(1, (fin_mes - m).days + 1), n)
            resp = np.clip(np.round(rng.normal(c, 1.1, (n, 5))), 1, 10).astype(int)
            enc = pd.DataFrame(resp, columns=PREGUNTAS)
            enc.insert(0, "sucursal", suc)
            enc.insert(0, "fecha", [(m + pd.Timedelta(days=int(x))).strftime("%Y-%m-%d") for x in dias_r])
            enc_list.append(enc)

    enc_all = pd.concat(enc_list, ignore_index=True).sort_values(["fecha", "sucursal"], ignore_index=True)
    return {
        "Diario": pd.concat(d_list, ignore_index=True).sort_values(["fecha", "sucursal"], ignore_index=True),
        "RH_mensual": pd.concat(rh_list, ignore_index=True),
        "Encuesta_equipo": enc_all,
        "Sucursales": pd.DataFrame({"sucursal": marca["sucursales"],
                                    "kiosco": ["sí" if s in piloto else "no" for s in marca["sucursales"]]}),
        "Config": pd.DataFrame({"clave": ["inicio_plan"], "valor": [inicio_plan.strftime("%Y-%m-%d")]}),
    }


def simular_dias(marca: dict, fechas, inicio_plan) -> pd.DataFrame:
    """Renglones nuevos de la pestaña Diario para las fechas dadas (botón 'Simular cierre del día')."""
    rng = np.random.default_rng()
    piloto = set(marca.get("piloto_kioscos", []))
    return pd.concat([diario(fechas, s, _Suc(s, s in piloto), inicio_plan, rng) for s in marca["sucursales"]],
                     ignore_index=True)
