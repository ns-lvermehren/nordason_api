from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import upload, fuzzy, freigabe

app = FastAPI(title="Nordason API")

# CORS für Appsmith
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # später auf Appsmith-URL einschränken
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router,   prefix="/upload",   tags=["upload"])
app.include_router(fuzzy.router,    prefix="/fuzzy",    tags=["fuzzy"])
app.include_router(freigabe.router, prefix="/freigabe", tags=["freigabe"])

@app.get("/health")
def health():
    return {"status": "ok"}