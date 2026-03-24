# routers/upload.py
import tempfile
import os
import json
from collections import defaultdict
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

    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        nodes, beziehungen = parse_excel_bom(tmp_path)

        if not nodes:
            raise HTTPException(
                400,
                "Keine Daten gefunden — prüfe ob das erste Sheet "
                "ab Zeile 3 Daten enthält."
            )

        with get_conn(user) as conn:
            cur = conn.cursor()

            try:
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
                        # Fuzzy-Hits vorberechnen
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

                # ── Polybag-Wrapper erkennen ──────────────────────────
                # Sub-Assembly mit genau einem Child und qty=1
                # → Child bekommt polybag=True
                # → Wrapper-Node aus staging entfernt
                # → BOM-Beziehung direkt Package → Child

                sub_children: dict[str, list] = defaultdict(list)
                for parent_ref, child_ref, qty in beziehungen:
                    if parent_ref is not None:
                        sub_children[parent_ref].append((child_ref, qty))

                polybag_wrapper: set[str] = set()
                polybag_child_map: dict[str, str] = {}  # wrapper → child

                for sub_ref, children in sub_children.items():
                    # Nur echte Sub-Assemblies (P-Refs) prüfen
                    # Set-Refs (NRV_...) und Package-Refs ausschließen
                    node = next(
                        (n for n in nodes if n.temp_ref == sub_ref), None
                    )
                    if node is None:
                        continue
                    # Nur Ebene-3 Nodes (haben selbst einen Parent
                    # der wiederum einen Parent hat)
                    if node.article_type not in ('Set', 'Assembly', 'Package'):
                        continue
                    if len(children) == 1 and children[0][1] == 1.0:
                        polybag_wrapper.add(sub_ref)
                        polybag_child_map[sub_ref] = children[0][0]

                # Child-Artikel als polybag markieren
                for wrapper_ref, child_ref in polybag_child_map.items():
                    cur.execute("""
                        UPDATE staging_artikel
                        SET polybag = true
                        WHERE version_id = %s AND temp_ref = %s
                    """, (version_id, child_ref))

                # Wrapper aus staging_artikel entfernen
                for wrapper_ref in polybag_wrapper:
                    cur.execute("""
                        DELETE FROM staging_artikel
                        WHERE version_id = %s AND temp_ref = %s
                    """, (version_id, wrapper_ref))

                # BOM-Beziehungen dedupliziert einfügen
                # Polybag-Wrapper werden übersprungen / umgeschrieben
                seen_beziehungen: set = set()

                for parent_ref, child_ref, qty in beziehungen:
                    # Wrapper als Parent → direkt zum echten Child
                    if parent_ref in polybag_wrapper:
                        continue  # diese Zeile überspringen
                    # Wrapper als Child → umschreiben auf echten Child
                    if child_ref in polybag_wrapper:
                        echtes_child = polybag_child_map[child_ref]
                        key = (parent_ref, echtes_child)
                        if key not in seen_beziehungen:
                            seen_beziehungen.add(key)
                            cur.execute("""
                                INSERT INTO staging_bom
                                    (version_id, parent_temp_ref,
                                     child_temp_ref, qty)
                                VALUES (%s, %s, %s, %s)
                            """, (version_id, parent_ref, echtes_child, qty))
                        continue

                    key = (parent_ref, child_ref)
                    if key not in seen_beziehungen:
                        seen_beziehungen.add(key)
                        cur.execute("""
                            INSERT INTO staging_bom
                                (version_id, parent_temp_ref,
                                 child_temp_ref, qty)
                            VALUES (%s, %s, %s, %s)
                        """, (version_id, parent_ref, child_ref, qty))

            finally:
                cur.close()

        return {
            "version_id":        version_id,
            "artikel_neu":       neue,
            "artikel_bekannt":   bekannt,
            "artikel_gesamt":    len(nodes),
            "beziehungen":       len(seen_beziehungen),
            "polybag_wrapper":   len(polybag_wrapper),
            "status":            "staging",
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(500, f"Upload fehlgeschlagen: {str(e)}")

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)