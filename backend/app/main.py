from fastapi import FastAPI

from .routers import orders, sync, users, devices, treasury, collaterals

app = FastAPI(
    title="CapiLink API",
    description="Backend de distribución de fondos y liquidación de última milla",
    version="1.0.0",
)

app.include_router(users.router)
app.include_router(devices.router)
app.include_router(treasury.router)
app.include_router(collaterals.router)
app.include_router(orders.router)
app.include_router(sync.router)


@app.get("/health")
def health():
    return {"status": "ok"}
