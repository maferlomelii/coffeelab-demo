# CoffeeLab · Tablero de operación (demo)

Demo con **datos ficticios** de una plataforma de KPIs para CoffeeLab (15 sucursales, 7 indicadores del plan).
Lee un Google Sheet y se actualiza sola cada 30 segundos. Usuario `demo`, contraseña `demo1234`.

## Archivos
| Archivo | Qué es |
|---|---|
| `app.py` | La app (pantallas) |
| `motor.py` | Cálculos: traduce las pestañas del Sheet, KPIs, semáforo, alertas |
| `datos_demo.py` | Genera los datos ficticios (y el botón "Simular cierre del día") |
| `report.py` | Reporte mensual en PDF |
| `marca.yaml` | **Todo lo del cliente**: nombre, colores, sucursales, metas |
| `.streamlit/config.toml` | Colores y tipografías de Streamlit |
| `config.example.yaml` | Usuario demo |

## Pestañas del Google Sheet
- `Diario`: fecha, sucursal, pedidos, pedidos_rehechos, tiempo_min, ventas_mxn, encuestas, satisfechos
- `RH_mensual`: mes, sucursal, plantilla, bajas, certificados
- `Encuesta_equipo`: fecha, sucursal, carga, capacitacion, trato_gerente, horario, seguir_6_meses (1 a 10)
- `Sucursales`: sucursal, kiosco
- `Config`: clave, valor (inicio_plan)

No cambies nombres de pestañas ni de columnas.

## Secretos (Streamlit Cloud → Settings → Secrets)
```
SHEET_ID = "el id que está en el link del Sheet"
GOOGLE_SERVICE_ACCOUNT_JSON = '''pega aquí todo el contenido del .json de la cuenta de servicio'''
```
Sin secretos, la app funciona en **modo demo** con los mismos datos generados en memoria.

Nunca subas a GitHub el `.json` de la cuenta de servicio.
