# Gmail Cleaner

Herramienta local para detectar y eliminar spam, phishing y listas indeseadas de Gmail. Incluye detección de brechas de datos y opt-out semi-automatizado de data brokers.

## Características

- **Multi-cuenta** — Agrega varias cuentas Gmail con wizard guiado
- **Scan de bandeja** — Detecta spam, phishing y newsletters por cabeceras de email
- **Desuscripción automática** — Usa el header `List-Unsubscribe` para salir de listas legítimas
- **Bloqueo de remitentes** — Crea filtros Gmail para enviar spam/phishing directo a la papelera
- **Detección de brechas** — Verifica tu email contra Have I Been Pwned
- **Opt-out data brokers** — Solicitudes semi-automatizadas a ~20 data brokers
- **Tracking en tiempo real** — Dashboard con SSE que muestra el estado de opt-outs en vivo
- **Extensión Chrome** — Badge y popup con resumen del estado de tu cuenta

## Instalación

### 1. Configurar Google Cloud Console

1. Ir a [console.cloud.google.com](https://console.cloud.google.com)
2. Crear un proyecto nuevo
3. Habilitar la **Gmail API**
4. Ir a "Credenciales" → Crear credenciales → **OAuth 2.0 Client ID**
   - Tipo: **Web Application**
   - URI de redirección autorizado: `http://localhost:8000/oauth/callback`
5. Descargar el JSON → renombrarlo como `credentials.json` → colocarlo en la carpeta `credentials/`

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurar entorno

```bash
cp .env.example .env
# Editar .env si necesitas cambiar algún valor
```

### 4. Ejecutar la app

```bash
uvicorn backend.main:app --reload
```

Abrir `http://localhost:8000` en el browser — el wizard de onboarding te guiará.

---

## Extensión Chrome

1. Abrir `chrome://extensions/` → activar **"Developer mode"**
2. Clic en **"Load unpacked"** → seleccionar la carpeta `chrome-extension/`
3. La primera vez que abres el popup, confirma la URL del servidor (default: `http://localhost:8000`)

La extensión muestra un badge con el número de issues activos y permite escanear/abrir el dashboard desde cualquier pestaña.

---

## Arquitectura

```
backend/
├── main.py          # FastAPI app, todas las rutas
├── database.py      # SQLAlchemy ORM, init de DB
├── accounts.py      # CRUD multi-cuenta
├── gmail_client.py  # OAuth2 + Gmail API wrapper
├── spam_analyzer.py # Detección spam/phishing
├── unsubscriber.py  # List-Unsubscribe automation
├── blocker.py       # Filtros Gmail
├── breach_checker.py# HIBP API
├── data_broker.py   # 20 data brokers + Playwright opt-out
└── sse.py           # Server-Sent Events para tracking real-time

frontend/
├── templates/       # Jinja2 HTML templates
└── static/          # CSS + JS (app.js, tracking.js)

chrome-extension/    # Manifest V3
```

**Base de datos**: SQLite local (`data/gmail_cleaner.db`). Para migrar a PostgreSQL: cambiar `DATABASE_URL` en `.env` por `postgresql+asyncpg://...`.

---

## Limitaciones

- **Phishing**: Los emails de phishing puro **no** se desuscriben — solo se bloquean. Enviar unsubscribe a un phisher confirmaría que el email existe.
- **Data brokers**: El proceso de opt-out puede tardar días o semanas. Algunos brokers exigen confirmación manual.
- **HIBP**: Solo detecta brechas conocidas y publicadas. No cubre brechas no reportadas.
- **Eliminación de brechas**: No es posible borrar tu email de una brecha que ya ocurrió. El opt-out de data brokers reduce la exposición futura.
- **Extensión Chrome**: Requiere que la app local esté corriendo.

---

## Privacidad

- Todos los datos se guardan **localmente** en tu máquina
- Las credenciales OAuth y tokens se guardan en `credentials/` (excluidas de git)
- La única comunicación externa es: Gmail API (Google), HIBP API, y los sitios de data brokers durante opt-out
