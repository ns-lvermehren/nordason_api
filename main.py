# main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import traceback
from routers import upload, fuzzy, freigabe, artikel
from db import pool

app = FastAPI(title="Nordason API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    pool.open(wait=False)

@app.on_event("shutdown")
async def shutdown():
    pool.close()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "trace": traceback.format_exc()}
    )

app.include_router(upload.router,   prefix="/upload",   tags=["upload"])
app.include_router(fuzzy.router,    prefix="/fuzzy",    tags=["fuzzy"])
app.include_router(freigabe.router, prefix="/freigabe", tags=["freigabe"])
app.include_router(artikel.router,  prefix="/artikel",  tags=["artikel"])

@app.get("/health")
def health():
    return {"status": "ok"}