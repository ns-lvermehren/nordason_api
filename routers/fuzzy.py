from fastapi import APIRouter, Query
from db import get_conn

router = APIRouter()

@router.get("")
def fuzzy_suche(
    q: str = Query(..., min_length=2),
    article_type: str = Query(None),
    limit: int = Query(5),
):
    """
    Fuzzy-Suche in product_master.
    Wird von Appsmith live aufgerufen während der Einkauf tippt.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT internal_reference, name, article_type, score
                FROM fuzzy_match_artikel(%s, %s, %s, 0.25)
            """, (q, article_type, limit))

            treffer = cur.fetchall()

    return [
        {
            "internal_reference": t[0],
            "name":               t[1],
            "article_type":       t[2],
            "score":              t[3],
        }
        for t in treffer
    ]