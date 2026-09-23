# RutaCash — Arquitectura Técnica (Offline-First)

Alcance de este documento: motor de cotización, esquema de datos cifrado y
módulo de conciliación de cierre de caja, dentro de un patrón general para
conectividad limitada.

## 1. Patrón general: Local-First + Outbox

RutaCash sigue un patrón **local-first con cola de salida (Outbox pattern)**:

```
┌─────────────┐     escribe primero      ┌──────────────────────┐
│  UI del POS │ ───────────────────────▶ │ SQLCipher (AES-256)  │
└─────────────┘                          │  - client_transactions│
       │                                 │  - daily_settlements  │
       │  encola cambio                  │  - cash_balances      │
       ▼                                 │  - rate_snapshots      │
┌─────────────┐                          │  - sync_queue          │
│ sync_queue   │ ◀────────────────────── └──────────────────────┘
└─────────────┘
       │  JobScheduler/WorkManager detecta red
       ▼
┌─────────────┐   push idempotente (uuid)   ┌───────────────┐
│ SyncQueue    │ ──────────────────────────▶│ Backend/Tesorería│
│ Manager      │ ◀── backoff exponencial ── │ (cuando hay red) │
└─────────────┘                              └───────────────┘
```

Toda operación de negocio (una venta, un cierre) se confirma primero contra
la base local; la sincronización remota es un efecto secundario asíncrono,
nunca una condición para que el agente pueda operar. Esto garantiza que la
terminal es 100% funcional sin red.

## 2. Almacenamiento local seguro (SQLCipher AES-256)

- Toda la base de datos se cifra a nivel de archivo con SQLCipher
  (cifrado de página completo, no solo columnas sensibles).
- La clave de cifrado se deriva del PIN del operador con **Argon2id** o se
  recupera del **Keystore (Android) / Keychain (iOS)** protegido por
  biometría; nunca se persiste en texto plano ni se hardcodea.
- `pin_hash` en `local_settings` solo guarda el hash del PIN — se usa para
  verificar el desbloqueo local, no para derivar la clave de cifrado por
  sí solo (se combina con un salt del dispositivo).
- `journal_mode = WAL` protege contra corrupción de datos ante cierres
  forzados o caídas de batería en campo.
- El esquema completo está en `schema.sql`.

## 3. Motor de cotización (`quotation-engine.ts`)

- La app nunca calcula con una tasa "en vivo": siempre lee el último
  `rate_snapshot` cacheado en SQLCipher. Esto hace que la cotización
  funcione sin red y sea auditable (cada transacción guarda tanto
  `reference_rate_used` como `exchange_rate_used`).
- Regla central: `Tasa_Efectiva_Cliente = Tasa_Referencia * (1 - Margen_Operador)`.
- Si la última tasa cacheada supera los 30 minutos de antigüedad, se marca
  `isStale = true` para que la UI alerte al agente antes de cotizar montos
  grandes con una tasa potencialmente desactualizada — decisión de negocio
  que queda en manos del agente, no bloqueante.
- `quickConvert()` implementa la calculadora rápida digital → fiat con
  desglose inmediato del margen bruto, para que el agente vea su ganancia
  antes de confirmar.

## 4. Conciliación de cierre de caja (`reconciliation-engine.ts`)

- Balance físico: `Cash_Inicial − Σ(Efectivo_Entregado) + Σ(Efectivo_Cobrado)`.
- Deuda con proveedor de liquidez: `Σ(Efectivo_Entregado) / Tasa_Acordada_Con_Proveedor`.
- El motor separa el **cálculo** (determinista, contra los agregados de
  `client_transactions`) del **conteo físico** (`closingCashCounted`,
  ingresado manualmente por el agente), y expone la discrepancia entre
  ambos para control interno.
- `generatePlainTextReport()` produce el texto estructurado para
  compartir por WhatsApp/Telegram vía los Share Intents nativos del SO;
  la variante en imagen se resuelve renderizando ese mismo texto sobre un
  layout fijo y exportando a PNG (fuera del alcance de este módulo).

## 5. Sincronización en segundo plano (`sync-queue.ts`)

- Patrón Outbox: cada escritura de negocio encola una entrada en
  `sync_queue` con el `uuid` de la entidad como clave idempotente, para
  que reintentos duplicados no dupliquen datos en el backend.
- Se ejecuta desde **WorkManager** (Android) o **BGTaskScheduler** (iOS),
  disparado por detección de red o en ciclos periódicos.
- Backoff exponencial con jitter (base 5s, techo 15 min) evita saturar
  redes móviles inestables; tras `max_retries` (8) el ítem pasa a
  `FAILED` para revisión manual en vez de reintentar indefinidamente.
- Procesamiento por lotes (`batchSize`) para optimizar consumo de datos
  en conexiones 2G/3G intermitentes típicas de campo.

## 6. Resiliencia end-to-end

| Riesgo                          | Mitigación                                                   |
|----------------------------------|---------------------------------------------------------------|
| Pérdida de red mid-operación      | Escritura local primero; sync es asíncrono (Outbox)            |
| Corte de energía / cierre forzado | `WAL` + transacciones atómicas en SQLite                       |
| Tasa de cambio desactualizada     | Marca `isStale`, alerta en UI, nunca bloquea la operación      |
| Reintentos duplicados en sync      | `uuid` como clave idempotente en backend y en `sync_queue`     |
| Robo/pérdida del dispositivo       | Cifrado de archivo completo (SQLCipher) + PIN/biometría        |
| Descuadre de caja al cierre        | `cash_discrepancy` explícito, nunca oculto ni auto-corregido   |
