# CapiLink Backend

API en FastAPI + Postgres. Ver `../ARCHITECTURE.md` para el diseño completo.

## Arranque local (con Docker)

```bash
cd backend
docker compose up --build
```

Esto levanta Postgres en `localhost:5432` (aplicando automáticamente
`schema_postgres.sql` al crear el contenedor) y la API en `localhost:8000`.

Prueba con:
```bash
curl http://localhost:8000/health
```

## Arranque local (sin Docker)

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Necesitas un Postgres corriendo y el schema aplicado:
psql "postgresql://usuario:pass@localhost/capilink" -f ../schema_postgres.sql

export DATABASE_URL="postgresql+psycopg2://usuario:pass@localhost/capilink"
uvicorn app.main:app --reload
```

## Endpoints implementados en este esqueleto

- `POST /orders` — crea una orden (genera OTP, calcula HMAC, envía SMS).
- `POST /orders/{uuid}/resend-otp` — reenvía el OTP (genera uno nuevo; útil si el SMS original falló).
- `POST /orders/{uuid}/assign` — asigna la orden a un agente (valida saldo disponible vía ledger).
- `POST /orders/{uuid}/cancel` — cancela una orden PENDING o ASSIGNED; si ya estaba ASSIGNED, libera el monto comprometido de vuelta al disponible del agente (busca el `cash_pool_id` real en el ledger, no adivina).
- `GET /orders/{uuid}` — consulta una orden.
- `GET /sync/pull/{agent_id}` — el agente descarga sus órdenes asignadas.
- `POST /sync/push` — el agente sube entregas confirmadas offline (valida firma Ed25519).
- `POST /collaterals` — el agente bloquea colateral en USDT (estado `LOCKED`) antes de poder operar con efectivo de un proveedor.
- `POST /collaterals/{uuid}/release` — el proveedor libera el colateral del agente.
- `POST /collaterals/{uuid}/forfeit` — el proveedor ejecuta el colateral (ej. impago o pérdida del agente); acepta opcionalmente el `tx_hash` del pago on-chain resultante.
- `GET /collaterals/{uuid}` / `GET /collaterals?agente_id=&status=` — consulta de colaterales.
- `GET /health` — chequeo de salud.

## Envío de SMS (OTP)

Controlado por la variable `SMS_PROVIDER`:

- `SMS_PROVIDER=console` (default): no envía nada real, solo loguea el
  mensaje. Úsalo en desarrollo local y en tests — no requiere credenciales.
- `SMS_PROVIDER=twilio`: envío real vía Twilio. Requiere:

```bash
export SMS_PROVIDER=twilio
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Uno de los dos (se recomienda Messaging Service en producción,
# maneja pooling de números y compliance automáticamente):
export TWILIO_FROM_NUMBER=+15005550006
# export TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

O el equivalente en `backend/.env` (ver `docker-compose.yml`, ya pasa
estas variables al contenedor `api` si están en tu entorno).

**Comportamiento ante fallos:** un fallo de envío **nunca revierte la
creación de la orden** — la orden queda creada con `otp_sms_status=FAILED`
y `otp_sms_error` con el motivo. El campo es visible en `GET /orders/{uuid}`
para que el operador decida reintentar con `POST /orders/{uuid}/resend-otp`.
Internamente, `TwilioSMSProvider` ya reintenta solo los errores transitorios
de Twilio (rate limit, 5xx) con backoff — errores permanentes (número
inválido, credenciales) fallan de inmediato sin gastar reintentos.

## Pendiente para producción (fuera del alcance de este esqueleto)

- Autenticación/autorización (JWT o similar) — ningún endpoint aquí está protegido todavía.
- Migraciones con Alembic en vez de aplicar `schema_postgres.sql` a mano.
- Reenvío automático (job periódico) de OTPs en `otp_sms_status=FAILED` — hoy el reintento es manual vía `/resend-otp`.
- Tests automatizados (no hay ninguno todavía).
- Cliente Flutter real (SQLCipher + sync_queue + `device_signature_service.dart`) — hoy solo existen los archivos de referencia sueltos en la raíz del repo, no un proyecto Flutter completo.
