-- =====================================================================
-- CapiLink — Backend Schema (PostgreSQL)
-- Fuente de verdad. Ver ARCHITECTURE.md para el razonamiento de diseño.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- USERS
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    role            TEXT NOT NULL CHECK (role IN ('PROVEEDOR', 'AGENTE_CAMPO', 'CLIENTE')),
    phone_number    TEXT NOT NULL UNIQUE,
    full_name       TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
                        CHECK (status IN ('PENDING_VERIFICATION', 'ACTIVE', 'SUSPENDED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Un usuario puede tener varios dispositivos; cada dispositivo tiene su
-- propio par de llaves para firmar pruebas de entrega offline (§5 del doc).
CREATE TABLE devices (
    id              BIGSERIAL PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    public_key      TEXT NOT NULL,            -- Ed25519 pubkey, base64
    platform        TEXT CHECK (platform IN ('ANDROID', 'IOS')),
    app_version     TEXT,
    last_sync_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,               -- si se pierde/roba el teléfono
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_devices_user ON devices(user_id) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------
-- CASH POOLS  (caché de saldo; la verdad vive en cash_ledger_entries)
-- ---------------------------------------------------------------------
CREATE TABLE cash_pools (
    id              BIGSERIAL PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    proveedor_id    BIGINT NOT NULL REFERENCES users(id),
    -- Todo monto en unidad mínima (centavos). CUP y USD con 2 decimales -> x100.
    total_cup_minor         BIGINT NOT NULL DEFAULT 0,
    total_usd_minor         BIGINT NOT NULL DEFAULT 0,
    available_cup_minor     BIGINT NOT NULL DEFAULT 0,  -- caché, recalculado desde el ledger
    available_usd_minor     BIGINT NOT NULL DEFAULT 0,  -- caché, recalculado desde el ledger
    version         INT NOT NULL DEFAULT 0,             -- optimistic locking
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cash_pools_proveedor ON cash_pools(proveedor_id);

-- ---------------------------------------------------------------------
-- LEDGER FINANCIERO (append-only, fuente de verdad de todos los saldos)
-- ---------------------------------------------------------------------
CREATE TABLE cash_ledger_entries (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key UUID NOT NULL UNIQUE,      -- generado en el cliente que originó el evento
    cash_pool_id    BIGINT NOT NULL REFERENCES cash_pools(id),
    agente_id       BIGINT REFERENCES users(id),          -- NULL para movimientos que no tocan a un agente
    order_id        BIGINT,                                -- FK lógica a distribution_orders (ver abajo, se agrega tras crear esa tabla)
    entry_type      TEXT NOT NULL CHECK (entry_type IN (
                        'PROVIDER_DEPOSIT',            -- + el proveedor mete efectivo al pool
                        'AGENT_ALLOCATION',            -- + proveedor entrega físico al agente
                        'ORDER_COMMITTED',             -- - se asigna una orden (dinero "en ruta")
                        'ORDER_CANCELLED_RELEASE',      -- + se libera el compromiso (orden cancelada)
                        'ORDER_DELIVERED_SETTLED',      -- neutro a nivel disponible; cierra ciclo
                        'AGENT_SETTLEMENT_RETURN'       -- - agente devuelve sobrante al proveedor
                     )),
    currency        TEXT NOT NULL CHECK (currency IN ('CUP', 'USD')),
    amount_minor    BIGINT NOT NULL,            -- con signo: + aumenta disponible, - lo reduce
    created_by_device_id BIGINT REFERENCES devices(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB
);
CREATE INDEX idx_ledger_pool ON cash_ledger_entries(cash_pool_id, currency);
CREATE INDEX idx_ledger_agente ON cash_ledger_entries(agente_id, currency) WHERE agente_id IS NOT NULL;
CREATE INDEX idx_ledger_order ON cash_ledger_entries(order_id) WHERE order_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- COLLATERALS
-- ---------------------------------------------------------------------
CREATE TABLE collaterals (
    id              BIGSERIAL PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    agente_id       BIGINT NOT NULL REFERENCES users(id),
    proveedor_id    BIGINT NOT NULL REFERENCES users(id),
    amount_usdt_minor BIGINT NOT NULL,           -- USDT con 6 decimales -> x1,000,000
    chain           TEXT NOT NULL DEFAULT 'TRC20' CHECK (chain IN ('TRC20', 'ERC20', 'BEP20')),
    status          TEXT NOT NULL DEFAULT 'LOCKED'
                        CHECK (status IN ('LOCKED', 'RELEASED', 'FORFEITED')),
    tx_hash         TEXT,
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_collaterals_agente ON collaterals(agente_id) WHERE status = 'LOCKED';

-- ---------------------------------------------------------------------
-- DISTRIBUTION ORDERS
-- ---------------------------------------------------------------------
CREATE TABLE distribution_orders (
    id                  BIGSERIAL PRIMARY KEY,
    uuid                UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    emisor_id           BIGINT NOT NULL REFERENCES users(id),
    beneficiario_phone  TEXT NOT NULL,
    destination_address TEXT NOT NULL,
    municipality        TEXT NOT NULL,
    amount_fiat_minor   BIGINT NOT NULL CHECK (amount_fiat_minor > 0),
    currency            TEXT NOT NULL CHECK (currency IN ('CUP', 'USD')),

    -- Seguridad OTP (ver ARCHITECTURE.md §4) — el OTP en texto plano NUNCA se guarda aquí.
    otp_hash            TEXT NOT NULL,           -- hex de HMAC-SHA256(order_secret, otp)
    otp_secret          TEXT NOT NULL,           -- 32 bytes random en base64; viaja al agente junto con la orden
    otp_expires_at      TIMESTAMPTZ NOT NULL,
    otp_attempts         INT NOT NULL DEFAULT 0,
    otp_max_attempts     INT NOT NULL DEFAULT 5,
    otp_locked_at        TIMESTAMPTZ,

    status              TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN (
                            'PENDING', 'ASSIGNED', 'IN_TRANSIT', 'DELIVERED',
                            'SETTLED', 'CANCELLED', 'FAILED'
                         )),
    assigned_agent_id   BIGINT REFERENCES users(id),
    assigned_at         TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_status ON distribution_orders(status);
CREATE INDEX idx_orders_agent ON distribution_orders(assigned_agent_id) WHERE assigned_agent_id IS NOT NULL;
CREATE INDEX idx_orders_municipality ON distribution_orders(municipality);

ALTER TABLE cash_ledger_entries
    ADD CONSTRAINT fk_ledger_order FOREIGN KEY (order_id) REFERENCES distribution_orders(id);

-- ---------------------------------------------------------------------
-- DELIVERIES  (prueba de entrega no-repudiable — ver ARCHITECTURE.md §5)
-- ---------------------------------------------------------------------
CREATE TABLE deliveries (
    id                  BIGSERIAL PRIMARY KEY,
    uuid                UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    order_id            BIGINT NOT NULL UNIQUE REFERENCES distribution_orders(id),
    agente_id           BIGINT NOT NULL REFERENCES users(id),
    device_id           BIGINT NOT NULL REFERENCES devices(id),

    assigned_at         TIMESTAMPTZ NOT NULL,
    delivered_at         TIMESTAMPTZ NOT NULL,     -- timestamp LOCAL del dispositivo al momento de la entrega
    synced_at            TIMESTAMPTZ,               -- cuándo llegó este registro al backend (puede ser mucho después)

    lat                 DOUBLE PRECISION,
    lng                 DOUBLE PRECISION,
    accuracy_m           DOUBLE PRECISION,

    -- Firma Ed25519 del payload {order_uuid, otp_hash, lat, lng, delivered_at, device_id}
    -- calculada en el dispositivo con la clave privada que nunca sale del keystore.
    proof_signature      TEXT NOT NULL,
    signature_verified   BOOLEAN NOT NULL DEFAULT FALSE,  -- se marca TRUE tras validar contra devices.public_key

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_deliveries_agente ON deliveries(agente_id);

-- ---------------------------------------------------------------------
-- CONFLICTOS DE SINCRONIZACIÓN (para revisión manual — ver ARCHITECTURE.md §6.2)
-- ---------------------------------------------------------------------
CREATE TABLE sync_conflicts (
    id              BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_uuid     UUID NOT NULL,
    conflict_reason TEXT NOT NULL,
    incoming_payload JSONB NOT NULL,
    current_state_snapshot JSONB NOT NULL,
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by     BIGINT REFERENCES users(id),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- AUDITORÍA (trazabilidad — requisito explícito)
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_user_id   BIGINT REFERENCES users(id),
    actor_device_id BIGINT REFERENCES devices(id),
    action          TEXT NOT NULL,                -- ej. 'ORDER_CREATED', 'ORDER_ASSIGNED', 'DELIVERY_VERIFIED'
    entity_type     TEXT NOT NULL,
    entity_uuid     UUID NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_uuid);
CREATE INDEX idx_audit_actor ON audit_log(actor_user_id);

-- =====================================================================
-- VISTAS DE SALDO (derivadas del ledger, nunca almacenadas como verdad)
-- =====================================================================

-- Saldo disponible por agente y moneda:
--   Efectivo_Disponible = Asignado_Por_Proveedor - Σ(Órdenes_En_Ruta)
CREATE VIEW v_agent_available_balance AS
SELECT
    agente_id,
    currency,
    SUM(amount_minor) AS available_minor
FROM cash_ledger_entries
WHERE agente_id IS NOT NULL
GROUP BY agente_id, currency;

-- Saldo total del pool de un proveedor (para reconciliar contra la columna caché):
CREATE VIEW v_pool_available_balance AS
SELECT
    cash_pool_id,
    currency,
    SUM(amount_minor) AS available_minor
FROM cash_ledger_entries
GROUP BY cash_pool_id, currency;

-- =====================================================================
-- FUNCIÓN: refrescar la caché de cash_pools tras cada inserción en el ledger
-- (se llama dentro de la misma transacción que el INSERT del ledger)
-- =====================================================================
CREATE OR REPLACE FUNCTION refresh_cash_pool_cache(p_cash_pool_id BIGINT)
RETURNS void AS $$
BEGIN
    UPDATE cash_pools cp
    SET
        available_cup_minor = COALESCE((
            SELECT SUM(amount_minor) FROM cash_ledger_entries
            WHERE cash_pool_id = p_cash_pool_id AND currency = 'CUP'
        ), 0),
        available_usd_minor = COALESCE((
            SELECT SUM(amount_minor) FROM cash_ledger_entries
            WHERE cash_pool_id = p_cash_pool_id AND currency = 'USD'
        ), 0),
        version = version + 1,
        updated_at = now()
    WHERE cp.id = p_cash_pool_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_refresh_cash_pool_cache()
RETURNS trigger AS $$
BEGIN
    PERFORM refresh_cash_pool_cache(NEW.cash_pool_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ledger_insert_refresh_cache
AFTER INSERT ON cash_ledger_entries
FOR EACH ROW EXECUTE FUNCTION trg_refresh_cash_pool_cache();
