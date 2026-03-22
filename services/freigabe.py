from services.artikel_nummer import generiere_artikelnummer
from services.gtin import generiere_gtin


def freigabe_durchfuehren(version_id: int, user: str, conn) -> dict:
    with conn.cursor() as cur:

        # 1. Offene Positionen prüfen
        cur.execute("""
            SELECT COUNT(*) FROM staging_artikel
            WHERE version_id = %s AND match_status = 'offen'
        """, (version_id,))
        if cur.fetchone()[0] > 0:
            return {"ok": False, "fehler": "Noch offene Positionen vorhanden"}

        # 2. Neue Artikel anlegen
        cur.execute("""
            SELECT id, temp_ref, name, article_type, sellable
            FROM staging_artikel
            WHERE version_id = %s AND match_status = 'neu_anlegen'
        """, (version_id,))
        neue_artikel = cur.fetchall()

        for sa_id, temp_ref, name, article_type, sellable in neue_artikel:
            internal_reference = generiere_artikelnummer(conn, article_type)
            gtin = generiere_gtin(conn) if sellable else None

            cur.execute("""
                INSERT INTO product_master
                    (internal_reference, name, article_type, sellable, gtin)
                VALUES (%s, %s, %s, %s, %s)
            """, (internal_reference, name, article_type, sellable, gtin))

            # matched_ref setzen
            cur.execute("""
                UPDATE staging_artikel
                SET matched_ref = %s
                WHERE id = %s
            """, (internal_reference, sa_id))

        # 3. Referenzen in staging_bom auflösen
        cur.execute("""
            UPDATE staging_bom sb
            SET
                parent_ref = (
                    SELECT matched_ref FROM staging_artikel sa
                    WHERE sa.version_id  = sb.version_id
                      AND sa.temp_ref    = sb.parent_temp_ref
                ),
                child_ref = (
                    SELECT matched_ref FROM staging_artikel sa
                    WHERE sa.version_id = sb.version_id
                      AND sa.temp_ref   = sb.child_temp_ref
                )
            WHERE sb.version_id = %s
        """, (version_id,))

        # 4. In produktive bom schreiben
        cur.execute("""
            INSERT INTO bom (parent, child, qty)
            SELECT sb.parent_ref, sb.child_ref, sb.qty::int
            FROM staging_bom sb
            JOIN staging_artikel sa_child
              ON sa_child.temp_ref   = sb.child_temp_ref
             AND sa_child.version_id = sb.version_id
            WHERE sb.version_id = %s
              AND sa_child.match_status != 'ignorieren'
              AND sb.child_ref IS NOT NULL
            ON CONFLICT DO NOTHING
        """, (version_id,))

        # 5. Session freigeben
        cur.execute("""
            UPDATE bom_session bs
            SET status = 'freigegeben', freigegeben_am = now()
            FROM bom_version bv
            WHERE bv.session_id = bs.id AND bv.id = %s
        """, (version_id,))

    return {"ok": True, "version_id": version_id}