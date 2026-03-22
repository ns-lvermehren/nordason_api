import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from db import get_conn
from services.parser import parse_excel_bom

router = APIRouter()

@router.post("")
async def upload_bom(
    file:        UploadFile = File(...),
    session_id:  int        = Form(...),
    user:        str        = Form("system"),
):
    """
    Excel-Upload → parsed Hierarchie → schreibt in staging_artikel + staging_bom.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Nur Excel-Dateien erlaubt (.xlsx, .xls)")

    # Temporär speichern
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # Neue Version anlegen
        with get_conn(user) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bom_version (session_id, version_nr, kommentar)
                    SELECT %s,
                           COALESCE(MAX(version_nr), 0) + 1,
                           'Excel-Upload: ' || %s
                    FROM bom_version
                    WHERE session_id = %s
                    RETURNING id
                """, (session_id, file.filename, session_id))
                version_id = cur.fetchone()[0]

            # Excel parsen (Spalten anpassen falls nötig)
            zeilen = parse_excel_bom(
                pfad=tmp_path,
                ebenen_spalten=[0, 1, 2, 3],
                menge_spalte=4,
                einheit_spalte=5,
                artikeltyp_spalte=6,
            )

            with conn.cursor() as cur:
                # Staging-Artikel einfügen
                for i, z in enumerate(zeilen):
                    temp_ref = f"tmp_{version_id}_{i}"

                    cur.execute("""
                        INSERT INTO staging_artikel
                            (version_id, temp_ref, name, article_type, match_status)
                        VALUES (%s, %s, %s, %s, 'offen')
                    """, (version_id, temp_ref, z.bezeichnung, z.article_type))

                # Staging-BOM Beziehungen einfügen
                for i, z in enumerate(zeilen):
                    child_ref  = f"tmp_{version_id}_{i}"
                    parent_ref = f"tmp_{version_id}_{z.parent_idx}" \
                                 if z.parent_idx is not None else None

                    cur.execute("""
                        INSERT INTO staging_bom
                            (version_id, parent_temp_ref, child_temp_ref, qty, unit)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (version_id, parent_ref, child_ref,
                          z.menge or 1, z.einheit))

        return {
            "version_id": version_id,
            "artikel":    len(zeilen),
            "status":     "staging"
        }

    finally:
        os.unlink(tmp_path)