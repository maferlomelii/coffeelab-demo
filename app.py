"""CoffeeLab · Tablero de operación (DEMO con datos ficticios).

Lee un Google Sheet con datos ficticios de las 15 sucursales y muestra los 7 KPIs del plan
en tiempo casi real: lo que se registra en la app se escribe en el Sheet y aparece en segundos.

Modos:
  - Sheet: si hay credenciales de Google (secret GOOGLE_SERVICE_ACCOUNT_JSON) y SHEET_ID.
  - Demo sin Sheet: si no hay credenciales, genera los mismos datos en memoria.
Todo lo propio del cliente (nombre, colores, sucursales, metas) está en marca.yaml.
"""
import json
import os
import re
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

import datos_demo
import motor
from report import build_pdf

HERE = os.path.dirname(os.path.abspath(__file__))
REFRESH_SECONDS = 30
TABS = ["Diario", "RH_mensual", "Encuesta_equipo", "Sucursales", "Config"]

with open(os.path.join(HERE, "marca.yaml"), encoding="utf-8") as _f:
    MARCA = yaml.load(_f, Loader=SafeLoader)
C = MARCA["colores"]
KCFG = MARCA["kpis"]
SUCS = MARCA["sucursales"]
PILOTO = MARCA.get("piloto_kioscos", [])

st.set_page_config(page_title=MARCA["titulo_app"], page_icon=MARCA.get("icono", "📊"), layout="wide")

st.markdown(f"""
<style>
[data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3 {{ color: {C['oscuro']}; }}
[data-testid="stMain"] .block-container {{ padding-top: 2.2rem; max-width: 1300px; }}
.brand {{ font-family: 'Fraunces', Georgia, serif; font-weight: 700; font-size: 2rem; color: {C['claro']}; line-height: 1; }}
.brand small {{ display:block; font-family: 'DM Sans', sans-serif; font-weight: 500; font-size: .8rem;
               letter-spacing: .12em; text-transform: uppercase; color: {C['acento_claro']}; margin-top: .4rem; }}
.kpi {{ background: {C['tarjeta']}; border: 1px solid {C['linea']}; border-radius: 14px; padding: 14px 16px 12px;
        height: 100%; }}
.kpi .n {{ font-size: .85rem; color: {C['gris']}; font-weight: 600; }}
.kpi .v {{ font-family: 'Fraunces', Georgia, serif; font-size: 2.1rem; font-weight: 700; color: {C['oscuro']}; line-height: 1.15; }}
.kpi .m {{ font-size: .82rem; color: {C['gris']}; margin: 2px 0 8px; }}
.kpi .d-bien {{ color: {C['verde']}; font-weight: 700; }}
.kpi .d-mal {{ color: {C['rojo']}; font-weight: 700; }}
.pill {{ display:inline-block; font-size: .75rem; font-weight: 700; padding: 2px 10px; border-radius: 99px; color: #fff; }}
.pill.verde {{ background: {C['verde']}; }} .pill.amarillo {{ background: {C['amarillo']}; }}
.pill.rojo {{ background: {C['rojo']}; }} .pill.gris {{ background: {C['gris']}; }}
.palabras {{ background: {C['oscuro']}; color: {C['claro']}; border-radius: 14px; padding: 16px 20px; font-size: 1.02rem; line-height: 1.55; }}
.palabras b {{ color: {C['acento_claro']}; }}
.alerta {{ background: {C['tarjeta']}; border: 1px solid {C['linea']}; border-left: 6px solid {C['gris']};
           border-radius: 12px; padding: 12px 16px; margin-bottom: 10px; }}
.alerta.a-rojo {{ border-left-color: {C['rojo']}; }} .alerta.a-naranja {{ border-left-color: {C['amarillo']}; }}
.alerta.a-verde {{ border-left-color: {C['verde']}; }}
.alerta .t {{ font-weight: 700; color: {C['oscuro']}; }} .alerta .x {{ color: #4A3B31; font-size: .95rem; }}
.vivo {{ display:inline-block; background: {C['verde']}; color:#fff; font-size:.72rem; font-weight:700;
         padding: 2px 9px; border-radius: 99px; margin-left: 6px; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] {{ padding: .45rem .8rem; border-radius: 10px; margin-bottom: .2rem; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {{ background: {C['acento_claro']}; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {{ color: {C['oscuro']}; font-weight: 700; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child {{ display: none; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- conexión al Sheet
def secreto(nombre, defecto=None):
    try:
        if nombre in st.secrets:
            return st.secrets[nombre]
    except Exception:
        pass
    return os.environ.get(nombre, defecto)


def creds_google():
    raw = secreto("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    p = os.path.join(HERE, "service_account.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


SHEET_ID = secreto("SHEET_ID", MARCA.get("sheet_id"))
MODO = "sheet" if (creds_google() and SHEET_ID) else "demo"


@st.cache_resource(show_spinner=False)
def _libro():
    import gspread
    from google.oauth2.service_account import Credentials
    cr = Credentials.from_service_account_info(creds_google(),
                                               scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(cr).open_by_key(SHEET_ID)


@st.cache_data(ttl=REFRESH_SECONDS, show_spinner="Leyendo el Sheet…")
def leer_sheet():
    libro = _libro()
    tabs = {}
    for ws in libro.worksheets():
        if ws.title in TABS:
            tabs[ws.title] = pd.DataFrame(ws.get_all_records(value_render_option="UNFORMATTED_VALUE"))
    L, avisos = motor.traducir(tabs, MARCA["cliente"])
    return tabs, L, motor.pivote_diario(L), avisos, datetime.now(), libro.title


@st.cache_data(show_spinner=False)
def datos_en_memoria(hoy: date):
    tabs = datos_demo.generar(MARCA, hoy)
    L, avisos = motor.traducir(tabs, MARCA["cliente"])
    return tabs, L, motor.pivote_diario(L), avisos


def leer():
    """(tabs, L, D, avisos, leido, origen). L = formato largo, D = pivote diario."""
    if MODO == "sheet":
        return leer_sheet()
    tabs, L, D, avisos = datos_en_memoria(date.today())
    extra = {k: v for k, v in st.session_state.get("extra", {}).items() if v}
    if extra:
        tabs = {k: v.copy() for k, v in tabs.items()}
        for tab, filas in extra.items():
            tabs[tab] = pd.concat([tabs[tab], pd.DataFrame(filas)], ignore_index=True)
        L, avisos = motor.traducir(tabs, MARCA["cliente"])
        D = motor.pivote_diario(L)
    return tabs, L, D, avisos, datetime.now(), "datos en memoria"


def escribir(tab: str, df: pd.DataFrame):
    """Agrega renglones al final de una pestaña (en el Sheet o en memoria)."""
    if MODO == "sheet":
        ws = _libro().worksheet(tab)
        cols = ws.row_values(1)
        valores = df.reindex(columns=cols).fillna("").astype(object).values.tolist()
        ws.append_rows(valores, value_input_option="USER_ENTERED")
        leer_sheet.clear()
    else:
        st.session_state.setdefault("extra", {}).setdefault(tab, []).extend(df.to_dict("records"))


# ----------------------------------------------------------------------- login
def to_plain(obj):
    if hasattr(obj, "items"):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


def config_login():
    try:
        if "credentials" in st.secrets and "auth_cookie" in st.secrets:
            return {"credentials": to_plain(st.secrets["credentials"]), "cookie": to_plain(st.secrets["auth_cookie"])}
    except Exception:
        pass
    p = os.path.join(HERE, "config.yaml")
    if not os.path.exists(p):
        p = os.path.join(HERE, "config.example.yaml")
    with open(p, encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)


cfg_login = config_login()
auth = stauth.Authenticate(cfg_login["credentials"], cfg_login["cookie"]["name"],
                           cfg_login["cookie"]["key"], cfg_login["cookie"]["expiry_days"])
if st.session_state.get("authentication_status") is not True:
    st.markdown(f"<style>.stApp {{ background: {C['oscuro']}; }} [data-testid='stHeader'] {{ background: transparent; }}"
                f"[data-testid='stForm'] {{ background: {C['tarjeta']} !important; border-radius: 18px !important; border: none !important;"
                f" padding: 1.4rem 1.6rem !important; box-shadow: 0 12px 40px rgba(0,0,0,.35); }}</style>",
                unsafe_allow_html=True)
_, col_login, _ = st.columns([1, 1.4, 1])
with col_login:
    marca_slot = st.empty()
    if st.session_state.get("authentication_status") is not True:
        marca_slot.markdown(
            f"<div style='text-align:center;margin:3rem 0 1.5rem'><div class='brand' style='font-size:3rem'>"
            f"{MARCA['cliente']}<small>{MARCA['titulo_app'].split('·')[-1].strip()}</small></div></div>",
            unsafe_allow_html=True)
    auth.login(location="main", fields={"Form name": "Iniciar sesión", "Username": "Usuario",
                                        "Password": "Contraseña", "Login": "Entrar"})
estado_login = st.session_state.get("authentication_status")
if estado_login is False:
    with col_login:
        st.error("Usuario o contraseña incorrectos.")
    st.stop()
if estado_login is None:
    with col_login:
        st.markdown(f"<p style='color:{C['claro']};text-align:center'>Demo: usuario <b>demo</b> · contraseña <b>demo1234</b></p>",
                    unsafe_allow_html=True)
    st.stop()
marca_slot.empty()

# ------------------------------------------------------------------- barra lateral
PAGINAS = ["📊 Resumen", "🏪 Sucursales", "🚨 Alertas", "📝 Registrar datos", "📄 Reporte"]
with st.sidebar:
    st.markdown(f"<div class='brand'>{MARCA['cliente']}<small>Tablero de operación</small></div>", unsafe_allow_html=True)
    st.write("")
    pagina = st.radio("Sección", PAGINAS, label_visibility="collapsed", key="pagina")
    st.divider()
    en_vivo = st.toggle("Actualizar en vivo", value=True, help=f"Vuelve a leer el Sheet cada {REFRESH_SECONDS} segundos.")
    if st.button("🔄 Actualizar ahora", width="stretch"):
        leer_sheet.clear()
        st.rerun()
    st.caption(f"👤 {st.session_state.get('name', '')}")
    auth.logout("Cerrar sesión", "sidebar")


# ------------------------------------------------------------------- piezas visuales
def tarjeta(kp: str, v, vprev, col):
    cfg = KCFG[kp]
    e, txt = motor.estado(kp, v, cfg)
    delta = ""
    if pd.notna(v) and vprev is not None and pd.notna(vprev):
        dif = v - vprev
        if abs(dif) >= 0.05:
            bien = (dif > 0) == cfg["mas_es_mejor"]
            u = {"tiempo": " min", "clima": ""}.get(kp, " pts")
            delta = f"<span class='{'d-bien' if bien else 'd-mal'}'>{'▲' if dif > 0 else '▼'} {abs(dif):.1f}{u}</span> vs. anterior"
    meta = motor.fmt(kp, cfg["meta"], cfg) if kp != "ventas" else f"+{cfg['meta']}% o más"
    col.markdown(f"<div class='kpi'><div class='n'>{cfg['nombre']}</div><div class='v'>{motor.fmt(kp, v, cfg)}</div>"
                 f"<div class='m'>Meta {meta}<br>{delta or '&nbsp;'}</div><span class='pill {e}'>{txt}</span></div>",
                 unsafe_allow_html=True)


def fila_tarjetas(k, kprev):
    c1 = st.columns(4)
    for kp, col in zip(motor.ORDEN_KPIS[:4], c1):
        tarjeta(kp, k[kp], kprev.get(kp), col)
    st.write("")
    c2 = st.columns(4)
    for kp, col in zip(motor.ORDEN_KPIS[4:], c2):
        tarjeta(kp, k[kp], kprev.get(kp), col)


def grafica(s: pd.DataFrame, kp: str, inicio_plan, s2: pd.DataFrame | None = None, nombres=("Valor", "")):
    cfg = KCFG[kp]
    s = s.assign(serie=nombres[0])
    if s2 is not None and not s2.empty:
        s = pd.concat([s, s2.assign(serie=nombres[1])])
    colores = alt.Scale(domain=[n for n in nombres if n], range=[C["acento"], C["gris"]])
    base = alt.Chart(s).encode(
        x=alt.X("periodo:T", title=None, axis=alt.Axis(labelExpr="date(datum.value) + ' ' + ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][month(datum.value)]",
                                                       labelOverlap=False, labelAngle=0, tickCount=8)),
        y=alt.Y("valor:Q", title=cfg["nombre"], scale=alt.Scale(zero=False)),
        color=alt.Color("serie:N", scale=colores, legend=alt.Legend(orient="top", title=None) if s2 is not None else None),
        tooltip=[alt.Tooltip("periodo:T", title="Periodo", format="%d/%m/%Y"),
                 alt.Tooltip("valor:Q", title="Valor", format=".1f"), alt.Tooltip("serie:N", title="Serie")])
    capas = [base.mark_line(strokeWidth=3), base.mark_circle(size=40)]
    capas.append(alt.Chart(pd.DataFrame({"y": [cfg["meta"]], "t": [f"Meta {cfg['meta']}"]})).mark_rule(
        strokeDash=[6, 4], color=C["verde"], strokeWidth=2).encode(y="y:Q"))
    capas.append(alt.Chart(pd.DataFrame({"y": [cfg["meta"]], "t": ["Meta"]})).mark_text(
        align="left", dx=4, dy=-8, color=C["verde"], fontWeight="bold").encode(y="y:Q", x=alt.value(0), text="t:N"))
    if inicio_plan is not None and s["periodo"].min() <= inicio_plan:
        capas.append(alt.Chart(pd.DataFrame({"x": [inicio_plan]})).mark_rule(color=C["oscuro"], strokeDash=[2, 3]).encode(x="x:T"))
        capas.append(alt.Chart(pd.DataFrame({"x": [inicio_plan], "t": ["Inicio del plan"]})).mark_text(
            align="left", dx=4, dy=8, color=C["oscuro"]).encode(x="x:T", y=alt.value(0), text="t:N"))
    st.altair_chart(alt.layer(*capas).properties(height=300), width="stretch")


def alerta_html(prio, titulo, texto):
    n = motor.nivel(prio)
    clase = {"🔴": "a-rojo", "🟠": "a-naranja", "🟢": "a-verde"}[n]
    etiqueta = {"🔴": "Urgente", "🟠": "Importante", "🟢": "Bien"}[n]
    st.markdown(f"<div class='alerta {clase}'><div class='t'>{n} {etiqueta} · {titulo}</div><div class='x'>{texto}</div></div>",
                unsafe_allow_html=True)


# ------------------------------------------------------------------------ páginas
def pagina_resumen(L, D, hasta, dias, inicio_plan):
    ver = st.selectbox("Ver", ["Todas las sucursales"] + SUCS, key="ver")
    sucs = SUCS if ver == "Todas las sucursales" else [ver]
    k, kprev = motor.comparar(L, D, sucs, hasta, dias)
    T = motor.tabla_sucursales(L, D, SUCS, hasta, dias, KCFG)
    texto = motor.resumen(k, kprev, MARCA, T if len(sucs) > 1 else pd.DataFrame(), dias)
    if len(sucs) == 1:
        texto = texto.replace(MARCA["cliente"], f"la sucursal {ver}", 1)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    st.markdown(f"<div class='palabras'>{html}</div>", unsafe_allow_html=True)
    st.write("")
    fila_tarjetas(k, kprev)
    st.caption("Satisfacción, tiempo, pedidos incorrectos y ventas: " + ("últimos 7 días" if dias == 7 else "últimas 4 semanas")
               + ". Clima laboral, rotación y certificación: mes en curso contra el mes anterior.")

    st.subheader("¿Cómo vamos desde que empezó el plan?")
    kp = st.segmented_control("Indicador", motor.ORDEN_KPIS, format_func=lambda x: KCFG[x]["nombre"],
                              default="tiempo", key="kp_res", label_visibility="collapsed") or "tiempo"
    desde = inicio_plan - pd.Timedelta(days=60) if inicio_plan is not None else None
    grafica(motor.serie(L, D, kp, sucs, desde), kp, inicio_plan, nombres=(ver if len(sucs) == 1 else "CoffeeLab", ""))

    if len(sucs) > 1:
        st.subheader("¿Ya podemos abrir sucursales nuevas?")
        metas = motor.metas_apertura(k)
        ok = sum(m[3] for m in metas)
        cols = st.columns(4)
        for (kp_, v, meta, cumple), col in zip(metas, cols):
            cfg = KCFG[kp_]
            signo = "≥" if motor.METAS_APERTURA[kp_][1] else "≤"
            col.markdown(f"<div class='kpi'><div class='n'>{cfg['nombre']}</div><div class='v' style='font-size:1.6rem'>"
                         f"{motor.fmt(kp_, v, cfg)}</div><div class='m'>Para abrir: {signo} {motor.fmt(kp_, meta, cfg)}</div>"
                         f"<span class='pill {'verde' if cumple else 'rojo'}'>{'✓ Cumple' if cumple else '✗ Todavía no'}</span></div>",
                         unsafe_allow_html=True)
        st.write("")
        if ok == 4:
            st.success("Se cumplen las 4 metas: ya se pueden abrir las 2 sucursales de prueba.")
        else:
            st.info(f"Se cumplen {ok} de 4 metas. Abrimos cuando se cumplan las 4.")


def pagina_sucursales(L, D, hasta, dias, inicio_plan):
    T = motor.tabla_sucursales(L, D, SUCS, hasta, dias, KCFG)
    st.subheader("Las 15 sucursales, de la que mejor va a la que más apoyo necesita")
    st.caption("Verde: en meta · Amarillo: en camino · Rojo: atrasada. El texto de cada celda es el valor.")
    fondo = {"verde": "#D7EAE6", "amarillo": "#F6E6C4", "rojo": "#F3D3CE", "gris": "#EEEEEE"}
    vista = pd.DataFrame({"Sucursal": T["Sucursal"],
                          "Kiosco": ["Sí" if s in PILOTO else "No" for s in T["Sucursal"]]})
    for kp in motor.ORDEN_KPIS:
        vista[KCFG[kp]["nombre"]] = [motor.fmt(kp, v, KCFG[kp]) for v in T[kp]]
    vista["En meta"] = T["en_meta"].astype(int).astype(str) + " de 7"

    def pintar(col):
        if col.name not in [KCFG[k]["nombre"] for k in motor.ORDEN_KPIS]:
            return [""] * len(col)
        kp = next(k for k in motor.ORDEN_KPIS if KCFG[k]["nombre"] == col.name)
        return [f"background-color: {fondo[e]}" for e in T[f"_e_{kp}"]]

    st.dataframe(vista.style.apply(pintar), hide_index=True, width="stretch", height=565)

    st.subheader("Detalle de una sucursal")
    c1, c2 = st.columns([1, 2])
    suc = c1.selectbox("Sucursal", SUCS, index=SUCS.index(T.iloc[-1]["Sucursal"]), key="suc_det")
    kp = c2.selectbox("Indicador", motor.ORDEN_KPIS, format_func=lambda x: KCFG[x]["nombre"], key="kp_det")
    k, kprev = motor.comparar(L, D, [suc], hasta, dias)
    fila_tarjetas(k, kprev)
    st.write("")
    desde = inicio_plan - pd.Timedelta(days=60) if inicio_plan is not None else None
    grafica(motor.serie(L, D, kp, [suc], desde), kp, inicio_plan,
            motor.serie(L, D, kp, SUCS, desde), nombres=(suc, "Todas las sucursales"))

    if PILOTO:
        st.subheader("¿Funcionan los kioscos?")
        st.caption("Tiempo de atención semanal: sucursales con kiosco contra las demás.")
        otras = [s for s in SUCS if s not in PILOTO]
        grafica(motor.serie(L, D, "tiempo", PILOTO, desde), "tiempo", inicio_plan,
                motor.serie(L, D, "tiempo", otras, desde), nombres=("Con kiosco", "Sin kiosco"))


def pagina_alertas(L, D, hasta, dias):
    st.subheader("Qué atender primero")
    st.caption("Se calculan solas con los datos del Sheet. Rojo: urgente · Naranja: importante · Verde: va bien.")
    for prio, titulo, texto in motor.alertas(L, D, MARCA, hasta, dias):
        alerta_html(prio, titulo, texto)


PREG_TXT = {"carga": "¿Qué tan manejable es tu carga de trabajo en horas pico?",
            "capacitacion": "¿Sientes que recibiste la capacitación necesaria para tu puesto?",
            "trato_gerente": "¿Cómo calificas el trato y la comunicación con tu gerente?",
            "horario": "¿Tu horario te permite combinar el trabajo con tus estudios u otras actividades?",
            "seguir_6_meses": "¿Qué tan probable es que sigas trabajando aquí dentro de 6 meses?"}


def pagina_registrar(tabs, inicio_plan):
    destino = "el Google Sheet" if MODO == "sheet" else "la memoria de la app (modo demo)"
    st.caption(f"Todo lo que guardes aquí se escribe en {destino} y el tablero lo muestra en segundos.")
    t1, t2, t3 = st.tabs(["🧾 Cierre del día (gerente)", "💬 Encuesta del equipo (anónima)", "🎲 Simular datos"])
    with t1:
        with st.form("cierre", clear_on_submit=False):
            a, b = st.columns(2)
            suc = a.selectbox("Sucursal", SUCS)
            f = b.date_input("Fecha", value=date.today(), format="DD/MM/YYYY")
            a, b, c = st.columns(3)
            ped = a.number_input("Pedidos del día", 0, 3000, 420)
            reh = b.number_input("Pedidos que se rehicieron", 0, 3000, 20)
            tmin = c.number_input("Tiempo promedio de atención (min)", 0.0, 60.0, 8.5, step=0.1)
            a, b, c = st.columns(3)
            vta = a.number_input("Ventas del día (MXN)", 0, 1_000_000, 36000, step=500)
            enc = b.number_input("Encuestas QR respondidas", 0, 3000, 30)
            sat = c.number_input("De ellas, clientes satisfechos", 0, 3000, 27)
            if st.form_submit_button("Guardar cierre", type="primary"):
                if reh > ped or sat > enc:
                    st.error("Revisa los números: los rehechos no pueden ser más que los pedidos, ni los satisfechos más que las encuestas.")
                else:
                    escribir("Diario", pd.DataFrame([{"fecha": f.strftime("%Y-%m-%d"), "sucursal": suc, "pedidos": ped,
                                                      "pedidos_rehechos": reh, "tiempo_min": tmin, "ventas_mxn": vta,
                                                      "encuestas": enc, "satisfechos": sat}]))
                    st.success(f"Listo: se guardó el cierre de {suc} del {f:%d/%m/%Y}. Si ya había uno ese día, este lo reemplaza.")
    with t2:
        st.caption("Así la contestaría un colaborador desde su celular. No se guarda su nombre.")
        with st.form("encuesta"):
            suc_e = st.selectbox("Sucursal", SUCS, key="suc_enc")
            resp = {p: st.slider(txt, 1, 10, 7, key=f"p_{p}") for p, txt in PREG_TXT.items()}
            if st.form_submit_button("Enviar respuesta anónima", type="primary"):
                escribir("Encuesta_equipo", pd.DataFrame([{"fecha": date.today().strftime("%Y-%m-%d"), "sucursal": suc_e, **resp}]))
                st.success("Gracias. La respuesta ya cuenta en el clima laboral de este mes.")
    with t3:
        ultimo = motor.parse_fecha(tabs["Diario"]["fecha"]).max() if "Diario" in tabs and not tabs["Diario"].empty else None
        hoy = pd.Timestamp(date.today())
        faltan = pd.date_range(ultimo + pd.Timedelta(days=1), hoy) if ultimo is not None and ultimo < hoy else pd.DatetimeIndex([hoy])
        faltan = faltan[-31:]
        st.write(f"Último día con datos: **{ultimo:%d/%m/%Y}**." if ultimo is not None else "Todavía no hay datos.")
        st.caption("Genera el cierre ficticio de las 15 sucursales para los días que falten hasta hoy "
                   "(o vuelve a generar el de hoy). Sirve para que el demo siempre esté al día.")
        if st.button(f"Simular cierre de {len(faltan)} día(s)", type="primary"):
            with st.spinner("Escribiendo…"):
                escribir("Diario", datos_demo.simular_dias(MARCA, faltan, inicio_plan or hoy - pd.Timedelta(days=120)))
            st.success("Listo. Revisa el Resumen: ya incluye los días nuevos.")
    st.subheader("Últimos renglones de la pestaña Diario")
    if "Diario" in tabs:
        st.dataframe(tabs["Diario"].tail(10).iloc[::-1], hide_index=True, width="stretch")


def pagina_reporte(L, D, hasta):
    st.subheader("Reporte mensual en PDF")
    meses = sorted(D["fecha"].dt.to_period("M").unique())[-6:]
    mes = st.selectbox("Mes", meses[::-1], format_func=lambda p: p.strftime("%m/%Y"))
    fin = min(mes.end_time.normalize(), hasta)
    dias = (fin - mes.start_time).days + 1
    k = motor.kpis(L, D, SUCS, fin, dias)
    k.update(motor.kpis_mensuales(L, SUCS, mes.start_time))
    kprev = motor.kpis(L, D, SUCS, mes.start_time - pd.Timedelta(days=1), (mes.start_time - (mes - 1).start_time).days)
    kprev.update(motor.kpis_mensuales(L, SUCS, (mes - 1).start_time))
    T = motor.tabla_sucursales(L, D, SUCS, fin, dias, KCFG)
    A = motor.alertas(L, D, MARCA, fin, 28)
    st.caption(f"Incluye los 7 indicadores del mes, la comparación con el mes anterior, el ranking de sucursales "
               f"y las 3 alertas principales. Periodo: {mes.start_time:%d/%m/%Y} al {fin:%d/%m/%Y}.")
    pdf = build_pdf(MARCA, mes.strftime("%m/%Y"), k, kprev, T, A)
    st.download_button("⬇️ Descargar reporte PDF", pdf, file_name=f"CoffeeLab_reporte_{mes.strftime('%Y_%m')}.pdf",
                       mime="application/pdf", type="primary")


# ------------------------------------------------------------------------ cuerpo
def cuerpo():
    try:
        tabs, L, D, avisos, leido, origen = leer()
    except Exception as e:  # noqa: BLE001
        st.error(f"No pude leer el Google Sheet. Revisa que esté compartido con la cuenta de servicio. ({type(e).__name__}: {str(e)[:150]})")
        st.stop()
    for a in avisos:
        st.warning(a)
    hasta = motor.ultima_fecha(L)
    if hasta is None:
        st.info("El Sheet todavía no tiene datos en la pestaña Diario.")
        return
    cfg_tab = tabs.get("Config", pd.DataFrame())
    inicio_plan = None
    if not cfg_tab.empty and "clave" in cfg_tab:
        v = cfg_tab.loc[cfg_tab["clave"] == "inicio_plan", "valor"]
        if not v.empty:
            inicio_plan = motor.parse_fecha(v).iloc[0]

    vivo = "<span class='vivo'>● EN VIVO</span>" if en_vivo and pagina in PAGINAS[:3] else ""
    st.markdown(f"<h1 style='margin-bottom:0'>{pagina.split(' ', 1)[1]}{vivo}</h1>", unsafe_allow_html=True)
    fuente = f"Google Sheet «{origen}»" if MODO == "sheet" else "datos ficticios en memoria (sin Sheet conectado)"
    st.caption(f"Datos al {hasta:%d/%m/%Y} · Fuente: {fuente} · Leído a las {leido:%H:%M:%S}")

    if pagina in ("📊 Resumen", "🏪 Sucursales", "🚨 Alertas"):
        gran = st.radio("Comparar", [7, 28], horizontal=True, key="gran",
                        format_func={7: "Semana vs. semana anterior", 28: "4 semanas vs. 4 anteriores"}.get)
    else:
        gran = 7
    if pagina == "📊 Resumen":
        pagina_resumen(L, D, hasta, gran, inicio_plan)
    elif pagina == "🏪 Sucursales":
        pagina_sucursales(L, D, hasta, gran, inicio_plan)
    elif pagina == "🚨 Alertas":
        pagina_alertas(L, D, hasta, gran)
    elif pagina == "📝 Registrar datos":
        pagina_registrar(tabs, inicio_plan)
    else:
        pagina_reporte(L, D, hasta)


if MODO == "demo":
    st.info("Modo demo: no hay Google Sheet conectado, así que los datos se generan dentro de la app. "
            "Lo que registres se guarda solo mientras la página esté abierta.")

if en_vivo and pagina in ("📊 Resumen", "🏪 Sucursales", "🚨 Alertas"):
    st.fragment(run_every=REFRESH_SECONDS)(cuerpo)()
else:
    cuerpo()
