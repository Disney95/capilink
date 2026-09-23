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
- `POST /orders/{uuid}/assign` — asigna la orden a un agente (valida saldo disponible vía ledger).
- `GET /orders/{uuid}` — consulta una orden.
- `GET /sync/pull/{agent_id}` — el agente descarga sus órdenes asignadas.
- `POST /sync/push` — el agente sube entregas confirmadas offline (valida firma Ed25519).
- `GET /health` — chequeo de salud.

## Pendiente para producción (fuera del alcance de este esqueleto)

- Autenticación/autorización (JWT o similar) — ningún endpoint aquí está protegido todavía.
- Integración real de SMS en `otp_service.send_otp_sms`.
- Registro de dispositivos (`POST /devices`) — el router de sync asume que el dispositivo ya existe en la tabla `devices`.
- Endpoints de proveedor (crear cash_pool, asignar agentes, ver colaterales).
- Migraciones con Alembic en vez de aplicar `schema_postgres.sql` a mano.
