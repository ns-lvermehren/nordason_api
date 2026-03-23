# routers/freigabe.py
from fastapi import APIRouter, HTTPException
from db import get_conn
from services.freigabe import freigabe_durchfuehren

router = APIRouter()


@router.post("/{version_id}")
def freigabe(
    version_id: int,
    user:       str = "system"
):
    """
    Bulk-Freigabe einer kompletten BOM-Version.
    Alle 'neu_anlegen' Artikel werden atomar angelegt.
    Blockiert wenn noch offene Positionen vorhanden.
    """
    with get_conn(user) as conn:
        result = freigabe_durchfuehren(version_id, user, conn)

    if not result["ok"]:
        raise HTTPException(400, detail=result["fehler"])

    return result