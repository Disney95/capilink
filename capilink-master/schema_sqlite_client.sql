-- =====================================================================
-- CapiLink — Client Schema (SQLite, cifrado con SQLCipher AES-256)
-- App del Agente de Distribución. Réplica parcial, nunca fuente de verdad.
-- Ver ARCHITECTURE.md §6 para el diseño de sincronización.
--
-- La clave de cifrado de SQLCipher se deriva de un secreto guardado en
-- Android Keystore / iOS Keychain y se pasa vía PRAGMA key al abrir la
-- conexión. No se guarda ni se deriva de nada hardcodeado en el binario.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Identidad local del dispositivo (una sola fila)
-- ---------------------------------------------------------------------
CREATE TABLE local_device (
    device_uuid     TEXT PRIMARY KEY,
    user_uuid       TEXT NOT NULL,          -- uuid del agente dueño de este dispositivo
    -- La clave PRIVADA Ed25519 vive en el Keystore/Keychore del SO, NO en esta tabla.
    -- Aquí solo se cachea la pública, por conveniencia, ya que no es sensible.
    public_key      TEXT NOT NULL,
    registered_at   TEXT NOT NULL,          -- ISO8601; se confirma al backend cuando hay señal
    last_sync_at    TEXT
);

-- ---------------------------------------------------------------------
-- Órdenes descargadas (subconjunto: solo las asignadas a este agente)
-- ---------------------------------------------------------------------
CREATE TABLE distribution_orders (
    uuid                 TEXT PRIMARY KEY,
    beneficiario_phone   TEXT NOT NULL,
    destination_address  TEXT NOT NULL,
    municipality         TEXT NOT NULL,
    amount_fiat_minor    INTEGER NOT NULL,
    currency             TEXT NOT NULL CHECK (currency IN ('CUP', 'USD')),

    -- Material necesario para verificar el OTP 100% offline (ver ARCHITECTURE.md §4).
    -- El OTP en texto plano NUNCA llega a este dispositivo.
    otp_hash             TEXT NOT NULL,
    otp_secret           TEXT NOT NULL,
    otp_expires_at        TEXT NOT NULL,
    otp_attempts          INTEGER NOT NULL DEFAULT 0,
    otp_max_attempts      INTEGER NOT NULL DEFAULT 5,
    otp_locked_at          TEXT,

    status                TEXT NOT NULL CHECK (status IN (
                              'ASSIGNED', 'IN_TRANSIT', 'DELIVERED', 'CANCELLED', 'FAILED'
                           )),
    assigned_at           TEXT NOT NULL,

    -- Metadatos de sincronización (patrón estándar en toda tabla replicada)
    server_updated_at     TEXT NOT NULL,     -- updated_at que traía el backend al bajar este registro
    dirty                 INTEGER NOT NULL DEFAULT 0,   -- 1 = hay cambios locales sin subir
    synced_at              TEXT
);
CREATE INDEX idx_local_orders_status ON distribution_orders(status);

-- ---------------------------------------------------------------------
-- Entregas confirmadas localmente (aún no sincronizadas hasta que synced_at != NULL)
-- ---------------------------------------------------------------------
CREATE TABLE deliveries (
    uuid                TEXT PRIMARY KEY,
    order_uuid          TEXT NOT NULL REFERENCES distribution_orders(uuid),
    device_uuid         TEXT NOT NULL,

    delivered_at         TEXT NOT NULL,      -- timestamp local (reloj del teléfono) del momento de entrega
    lat                 REAL,
    lng                 REAL,
    accuracy_m           REAL,

    proof_signature      TEXT NOT NULL,      -- firma Ed25519 generada localmente con la clave privada del keystore

    synced_at             TEXT               -- NULL hasta confirmar recepción del backend
);
CREATE INDEX idx_local_deliveries_pending ON deliveries(order_uuid) WHERE synced_at IS NULL;

-- ---------------------------------------------------------------------
-- Ledger local (espejo de los eventos financieros que ESTE dispositivo generó)
-- Se sube al backend, nunca se "resuelve" localmente contra otros dispositivos.
-- ---------------------------------------------------------------------
CREATE TABLE cash_ledger_entries_local (
    idempotency_key      TEXT PRIMARY KEY,   -- uuid generado en este dispositivo al crear el evento
    entry_type           TEXT NOT NULL CHECK (entry_type IN (
                             'ORDER_COMMITTED', 'ORDER_DELIVERED_SETTLED', 'ORDER_CANCELLED_RELEASE'
                          )),
    currency              TEXT NOT NULL CHECK (currency IN ('CUP', 'USD')),
    amount_minor          INTEGER NOT NULL,
    order_uuid            TEXT REFERENCES distribution_orders(uuid),
    created_at             TEXT NOT NULL,
    synced_at              TEXT
);

-- Saldo disponible LOCAL, calculado igual que la vista del backend (§3.1),
-- pero solo con lo que este dispositivo conoce (puede estar desactualizado
-- si el proveedor hizo una nueva asignación que aún no bajó por sync).
-- Se expone como vista, no como columna, para evitar que diverja de la realidad.
CREATE VIEW v_local_available_balance AS
SELECT
    currency,
    SUM(amount_minor) AS available_minor
FROM cash_ledger_entries_local
GROUP BY currency;

-- Nota de UX importante: como esta vista solo ve el ledger local, el agente
-- debe sincronizar periódicamente para que su "efectivo disponible" refleje
-- asignaciones nuevas hechas por el proveedor desde otro dispositivo/oficina.
-- La app debe mostrar claramente "última sincronización: hace X" junto al saldo.

-- ---------------------------------------------------------------------
-- OUTBOX / SYNC QUEUE — patrón transactional outbox (ver ARCHITECTURE.md §6.1)
-- Toda escritura de negocio offline se acompaña, en la MISMA transacción
-- SQLite, de una fila aquí. Es lo único que el motor de sincronización lee.
-- ---------------------------------------------------------------------
CREATE TABLE sync_queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type         TEXT NOT NULL CHECK (entity_type IN (
                            'distribution_orders', 'deliveries', 'cash_ledger_entries_local'
                         )),
    entity_uuid         TEXT NOT NULL,
    operation           TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE')),
    payload_json        TEXT NOT NULL,        -- snapshot completo de la fila al momento de encolar
    created_at          TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING', 'SYNCING', 'SYNCED', 'ERROR')),
    retries              INTEGER NOT NULL DEFAULT 0,
    last_error            TEXT,
    last_attempt_at        TEXT
);
CREATE INDEX idx_sync_queue_pending ON sync_queue(status, created_at) WHERE status = 'PENDING';

-- ---------------------------------------------------------------------
-- Ejemplo de transacción atómica al confirmar una entrega (pseudocódigo SQL,
-- ejecutar dentro de BEGIN IMMEDIATE ... COMMIT en la app):
-- ---------------------------------------------------------------------
-- BEGIN IMMEDIATE;
--
-- UPDATE distribution_orders
-- SET status = 'DELIVERED', dirty = 1
-- WHERE uuid = :order_uuid;
--
-- INSERT INTO deliveries (uuid, order_uuid, device_uuid, delivered_at, lat, lng, accuracy_m, proof_signature)
-- VALUES (:delivery_uuid, :order_uuid, :device_uuid, :now, :lat, :lng, :accuracy, :signature);
--
-- INSERT INTO cash_ledger_entries_local (idempotency_key, entry_type, currency, amount_minor, order_uuid, created_at)
-- VALUES (:ledger_uuid, 'ORDER_DELIVERED_SETTLED', :currency, 0, :order_uuid, :now);
--
-- INSERT INTO sync_queue (entity_type, entity_uuid, operation, payload_json, created_at)
-- VALUES ('distribution_orders', :order_uuid, 'UPDATE', :orders_snapshot_json, :now);
--
-- INSERT INTO sync_queue (entity_type, entity_uuid, operation, payload_json, created_at)
-- VALUES ('deliveries', :delivery_uuid, 'INSERT', :delivery_snapshot_json, :now);
--
-- COMMIT;
--
-- Si la app crashea a mitad de esto, SQLite garantiza que TODO o NADA de
-- lo anterior queda escrito — nunca un estado "DELIVERED" sin su fila de
-- sync_queue correspondiente, que es exactamente la garantía que se necesita.
