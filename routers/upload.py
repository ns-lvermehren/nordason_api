# routers/upload.py
import tempfile
import os
import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from db import get_conn
from services.parser import parse_excel_bom

router = APIRouter()


@router.post("")
async def upload_bom(
    file:       UploadFile = File(...),
    session_id: int        = Form(...),
    user:       str        = Form("system"),
):
    # Datei-Validierung
    allowed_extensions = ('.xlsx', '.xls')
    filename     = file.filename or ''
    content_type = file.content_type or ''

    if not (
        filename.lower().endswith(allowed_extensions) or
        'spreadsheet' in content_type or
        'excel' in content_type or
        'openxmlformats' in content_type
    ):
        raise HTTPException(
            400,
            f"Nur Excel-Dateien erlaubt "
            f"(erhalten: filename='{filename}', content_type='{content_type}')"
        )

    # Temporär speichern
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # Excel parsen
        nodes, beziehungen = parse_excel_bom(tmp_path)

        if not nodes:
            raise HTTPException(
                400,
                "Keine Daten gefunden — prüfe ob die Datei das BOM-Sheet "
                "enthält und ab Zeile 4 Daten hat."
            )

        with get_conn(user) as conn:
            with conn.cursor() as cur:

                # Neue Version anlegen
                cur.execute("""
                    INSERT INTO bom_version (session_id, version_nr, kommentar)
                    SELECT %s,
                           COALESCE(MAX(version_nr), 0) + 1,
                           'Excel-Upload: ' || %s
                    FROM bom_version
                    WHERE session_id = %s
                    RETURNING id
                """, (session_id, filename, session_id))
                version_id = cur.fetchone()[0]

                neue    = 0
                bekannt = 0

                for node in nodes:
                    if node.is_existing:
                        # Bereits in product_master → direkt als matched markieren
                        cur.execute("""
                            INSERT INTO staging_artikel
                                (version_id, temp_ref, name, article_type,
                                 match_status, matched_ref)
                            VALUES (%s, %s, %s, %s, 'matched', %s)
                            ON CONFLICT (version_id, temp_ref) DO NOTHING
                        """, (
                            version_id,
                            node.temp_ref,
                            node.name,
                            node.article_type,
                            node.temp_ref,
                        ))
                        bekannt += 1

                    else:
                        # Neu → Fuzzy-Hits vorberechnen
                        cur.execute("""
                            SELECT internal_reference, name, article_type, score
                            FROM fuzzy_match_artikel(%s, %s, 5, 0.25)
                        """, (node.name, node.article_type.lower()))
                        hits = cur.fetchall()

                        cur.execute("""
                            INSERT INTO staging_artikel
                                (version_id, temp_ref, name, article_type,
                                 match_status, fuzzy_hits)
                            VALUES (%s, %s, %s, %s, 'offen', %s)
                            ON CONFLICT (version_id, temp_ref) DO NOTHING
                        """, (
                            version_id,
                            node.temp_ref,
                            node.name,
                            node.article_type,
                            json.dumps([
                                {
                                    "ref":   h[0],
                                    "name":  h[1],
                                    "type":  h[2],
                                    "score": h[3],
                                }
                                for h in hits
                            ]),
                        ))
                        neue += 1

                # BOM-Beziehungen einfügen
                for parent_ref, child_ref, qty in beziehungen:
                    cur.execute("""
                        INSERT INTO staging_bom
                            (version_id, parent_temp_ref, child_temp_ref,
                             qty, unit)
                        VALUES (%s, %s, %s, %s, 'Stk')
                    """, (version_id, parent_ref, child_ref, qty))

                # Wurzeln (kein Parent) in staging_bom eintragen
                for node in nodes:
                    if node.parent_ref is None:
                        cur.execute("""
                            INSERT INTO staging_bom
                                (version_id, parent_temp_ref,
                                 child_temp_ref, qty)
                            VALUES (%s, NULL, %s, 1)
                        """, (version_id, node.temp_ref))

        return {
            "version_id":      version_id,
            "artikel_neu":     neue,
            "artikel_bekannt": bekannt,
            "artikel_gesamt":  len(nodes),
            "beziehungen":     len(beziehungen),
            "status":          "staging",
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(500, f"Upload fehlgeschlagen: {str(e)}")

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)