# services/freigabe.py
from services.artikel_nummer import generiere_artikelnummer
from services.gtin import generiere_gtin


class FreigabeFehler(Exception):
    """Wird geworfen wenn die Freigabe abgebrochen werden muss."""
    pass


def freigabe_durchfuehren(version_id: int, user: str, conn) -> dict:
    """
    Bulk-Freigabe einer kompletten BOM-Version.
    Alle 'neu_anlegen' Artikel werden in einer Transaktion angelegt.
    Alles oder nichts — bei Fehler wird alles zurückgerollt.
    """
    cur = conn.cursor()

    try:
        # 1. Sicherheitsprüfung: keine offenen Positionen
        cur.execute("""
            SELECT COUNT(*) FROM staging_artikel
            WHERE version_id = %s AND match_status = 'offen'
        """, (version_id,))
        offen = cur.fetchone()[0]
        if offen > 0:
            return {
                "ok":     False,
                "fehler": f"{offen} Positionen noch offen — "
                          f"bitte alle matchen oder ignorieren."
            }

        # 2. Alle neuen Artikel holen
        cur.execute("""
            SELECT id, temp_ref, name, article_type
            FROM staging_artikel
            WHERE version_id = %s
              AND match_status = 'neu_anlegen'
              AND matched_ref IS NULL
            ORDER BY id
        """, (version_id,))
        neue_artikel = cur.fetchall()

        # 3. Nummern vorab generieren und auf Duplikate prüfen
        # Alles oder nichts — erst alle Nummern generieren,
        # dann alle prüfen, dann alle einfügen
        geplante_artikel = []
        for sa_id, temp_ref, name, article_type in neue_artikel:
            internal_reference = generiere_artikelnummer(conn, article_type)

            # Prüfen ob Nummer bereits in product_master existiert
            cur.execute("""
                SELECT COUNT(*) FROM product_master
                WHERE internal_reference = %s
            """, (internal_reference,))
            if cur.fetchone()[0] > 0:
                raise FreigabeFehler(
                    f"Artikelnummer {internal_reference} bereits vergeben "
                    f"(Artikel: '{name}', temp_ref: '{temp_ref}'). "
                    f"Bitte Sequences prüfen und Freigabe wiederholen."
                )

            geplante_artikel.append((sa_id, temp_ref, name,
                                     article_type, internal_reference))

        # 4. Alle Artikel in product_master anlegen
        neu_angelegt = 0
        for sa_id, temp_ref, name, article_type, internal_reference \
                in geplante_artikel:

            cur.execute("""
                INSERT INTO product_master
                    (internal_reference, name, article_type, sellable)
                VALUES (%s, %s, %s, false)
            """, (internal_reference, name, article_type))

            # Status auf 'freigegeben' setzen (nicht 'matched')
            cur.execute("""
                UPDATE staging_artikel
                SET matched_ref        = %s,
                    internal_reference = %s,
                    match_status       = 'freigegeben'
                WHERE id = %s
            """, (internal_reference, internal_reference, sa_id))

            neu_angelegt += 1

        # 5. Referenzen in staging_bom auflösen
        cur.execute("""
            UPDATE staging_bom sb
            SET
                parent_ref = (
                    SELECT matched_ref
                    FROM staging_artikel sa
                    WHERE sa.version_id = sb.version_id
                      AND sa.temp_ref   = sb.parent_temp_ref
                ),
                child_ref = (
                    SELECT matched_ref
                    FROM staging_artikel sa
                    WHERE sa.version_id = sb.version_id
                      AND sa.temp_ref   = sb.child_temp_ref
                )
            WHERE sb.version_id = %s
        """, (version_id,))

        # 6. Prüfen ob alle Referenzen aufgelöst wurden
        cur.execute("""
            SELECT COUNT(*) FROM staging_bom
            WHERE version_id = %s
              AND child_ref IS NULL
        """, (version_id,))
        unaufgeloest = cur.fetchone()[0]
        if unaufgeloest > 0:
            raise FreigabeFehler(
                f"{unaufgeloest} BOM-Positionen konnten nicht aufgelöst "
                f"werden — bitte Review prüfen."
            )

        # 7. Bulk: alle eindeutigen Beziehungen in produktive bom schreiben
        cur.execute("""
            INSERT INTO bom (parent, child, qty)
            SELECT DISTINCT
                sb.parent_ref,
                sb.child_ref,
                sb.qty::int
            FROM staging_bom sb
            JOIN staging_artikel sa_child
              ON sa_child.temp_ref    = sb.child_temp_ref
             AND sa_child.version_id  = sb.version_id
            WHERE sb.version_id = %s
              AND sa_child.match_status != 'ignorieren'
              AND sb.child_ref IS NOT NULL
            ON CONFLICT DO NOTHING
        """, (version_id,))

        # 8. Session auf freigegeben setzen
        cur.execute("""
            UPDATE bom_session bs
            SET status         = 'freigegeben',
                freigegeben_am = now()
            FROM bom_version bv
            WHERE bv.session_id = bs.id
              AND bv.id         = %s
        """, (version_id,))

        return {
            "ok":           True,
            "version_id":   version_id,
            "neu_angelegt": neu_angelegt,
            "status":       "freigegeben",
        }

    except FreigabeFehler as e:
        # Transaktion wird von get_conn automatisch zurückgerollt
        return {
            "ok":     False,
            "fehler": str(e)
        }

    finally:
        cur.close()