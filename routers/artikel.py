# routers/artikel.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from db import get_conn

router = APIRouter()


class ArtikelPatch(BaseModel):
    name:          Optional[str]   = None
    gtin:          Optional[int]   = None
    polybag:       Optional[bool]  = None
    sellable:      Optional[bool]  = None
    article_type:  Optional[str]   = None


@router.patch("/{internal_reference}")
def patch_artikel(
    internal_reference: str,
    payload: ArtikelPatch,
    user: str = "system"
):
    # Nur gesetzte Felder updaten
    felder = payload.model_dump(exclude_none=True)

    if not felder:
        raise HTTPException(400, detail="Keine Felder zum Aktualisieren angegeben.")

    erlaubte_felder = {'name', 'gtin', 'polybag', 'sellable', 'article_type'}
    unbekannte = set(felder.keys()) - erlaubte_felder
    if unbekannte:
        raise HTTPException(400, detail=f"Unbekannte Felder: {unbekannte}")

    set_clause = ", ".join(f"{k} = %s" for k in felder)
    values = list(felder.values()) + [internal_reference]

    with get_conn(user) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE product_master
                SET {set_clause}
                WHERE internal_reference = %s
                RETURNING internal_reference, name, gtin,
                          polybag, sellable, article_type
                """,
                values
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    404,
                    detail=f"Artikel {internal_reference} nicht gefunden."
                )
        finally:
            cur.close()

    return {
        "ok":                 True,
        "internal_reference": row[0],
        "name":               row[1],
        "gtin":               row[2],
        "polybag":            row[3],
        "sellable":           row[4],
        "article_type":       row[5],
    }


@router.get("/{internal_reference}")
def get_artikel(internal_reference: str):
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT internal_reference, name, article_type,
                       gtin, polybag, sellable, created_at, updated_at,
                       import_version_id, import_session_id
                FROM product_master
                WHERE internal_reference = %s
            """, (internal_reference,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    404,
                    detail=f"Artikel {internal_reference} nicht gefunden."
                )
        finally:
            cur.close()

    return {
        "internal_reference": row[0],
        "name":               row[1],
        "article_type":       row[2],
        "gtin":               row[3],
        "polybag":            row[4],
        "sellable":           row[5],
        "created_at":         row[6],
        "updated_at":         row[7],
        "import_version_id":  row[8],
        "import_session_id":  row[9],
    }