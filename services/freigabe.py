# services/freigabe.py
from services.artikel_nummer import generiere_artikelnummer
from services.gtin import generiere_gtin, berechne_gtin14_aus_gtin13


class FreigabeFehler(Exception):
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

        # 2. Version und Session Info holen
        cur.execute("""
            SELECT bv.id, bv.session_id
            FROM bom_version bv
            WHERE bv.id = %s
        """, (version_id,))
        bv_row = cur.fetchone()
        if not bv_row:
            return {
                "ok":     False,
                "fehler": f"Version {version_id} nicht gefunden."
            }
        bv_id, bs_id = bv_row[0], bv_row[1]

        # 3. Alle neuen Artikel holen — Singles/Smallparts zuerst, Packages zuletzt
        # damit GTIN-13 der Children bereits vorhanden sind wenn Packages angelegt werden
        cur.execute("""
            SELECT id, temp_ref, name, article_type, polybag
            FROM staging_artikel
            WHERE version_id = %s
              AND match_status = 'neu_anlegen'
              AND matched_ref IS NULL
            ORDER BY
                CASE article_type
                    WHEN 'Single'    THEN 1
                    WHEN 'Smallpart' THEN 2
                    WHEN 'Assembly'  THEN 3
                    WHEN 'Set'       THEN 4
                    WHEN 'Package'   THEN 5
                    WHEN 'Template'  THEN 6
                    ELSE 7
                END,
                id
        """, (version_id,))
        neue_artikel = cur.fetchall()

        # 4. Artikelnummern vorab generieren und auf Duplikate prüfen
        geplante_artikel = []
        for sa_id, temp_ref, name, article_type, polybag in neue_artikel:

            internal_reference = generiere_artikelnummer(conn, article_type)

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

            geplante_artikel.append((
                sa_id, temp_ref, name,
                article_type, internal_reference,
                polybag or False
            ))

        # 5. Alle Artikel in product_master anlegen
        # Packages ohne GTIN — wird in Schritt 6b gesetzt
        neu_angelegt = 0
        for sa_id, temp_ref, name, article_type, internal_reference, polybag \
                in geplante_artikel:

            if article_type == 'Package':
                gtin = None  # wird nach BOM-Auflösung gesetzt
            else:
                gtin = generiere_gtin(conn)

            cur.execute("""
                INSERT INTO product_master
                    (internal_reference, name, article_type, sellable,
                     polybag, import_version_id, import_session_id, gtin)
                VALUES (%s, %s, %s, false, %s, %s, %s, %s)
            """, (internal_reference, name, article_type,
                  polybag, bv_id, bs_id, gtin))

            cur.execute("""
                UPDATE staging_artikel
                SET matched_ref        = %s,
                    internal_reference = %s,
                    match_status       = 'freigegeben'
                WHERE id = %s
            """, (internal_reference, internal_reference, sa_id))

            neu_angelegt += 1

        # 6. Referenzen in staging_bom auflösen
        cur.execute("""
            UPDATE staging_bom sb
            SET
                parent_ref = (
                    SELECT matched_ref FROM staging_artikel sa
                    WHERE sa.version_id = sb.version_id
                      AND sa.temp_ref   = sb.parent_temp_ref
                ),
                child_ref = (
                    SELECT matched_ref FROM staging_artikel sa
                    WHERE sa.version_id = sb.version_id
                      AND sa.temp_ref   = sb.child_temp_ref
                )
            WHERE sb.version_id = %s
        """, (version_id,))

        # 6b. GTIN-14 für neu angelegte Package-Artikel berechnen
        # Package → Child BOM-Beziehung → Child GTIN-13 → Package GTIN-14
        cur.execute("""
            SELECT DISTINCT
                sa_pkg.matched_ref  AS package_ref,
                pm_child.gtin       AS child_gtin
            FROM staging_bom sb
            JOIN staging_artikel sa_pkg
              ON sa_pkg.temp_ref   = sb.parent_temp_ref
             AND sa_pkg.version_id = sb.version_id
            JOIN staging_artikel sa_child
              ON sa_child.temp_ref   = sb.child_temp_ref
             AND sa_child.version_id = sb.version_id
            JOIN product_master pm_pkg
              ON pm_pkg.internal_reference = sa_pkg.matched_ref
            JOIN product_master pm_child
              ON pm_child.internal_reference = sa_child.matched_ref
            WHERE sb.version_id        = %s
              AND pm_pkg.article_type  = 'Package'
              AND sa_pkg.match_status  = 'freigegeben'
              AND pm_child.gtin        IS NOT NULL
              AND pm_pkg.gtin          IS NULL
        """, (version_id,))
        package_gtins = cur.fetchall()

        for package_ref, child_gtin in package_gtins:
            gtin14 = berechne_gtin14_aus_gtin13(child_gtin)
            cur.execute("""
                UPDATE product_master
                SET gtin = %s
                WHERE internal_reference = %s
            """, (gtin14, package_ref))

        # 7. Prüfen ob alle Referenzen aufgelöst wurden
        cur.execute("""
            SELECT COUNT(*) FROM staging_bom
            WHERE version_id = %s AND child_ref IS NULL
        """, (version_id,))
        unaufgeloest = cur.fetchone()[0]
        if unaufgeloest > 0:
            raise FreigabeFehler(
                f"{unaufgeloest} BOM-Positionen konnten nicht aufgelöst "
                f"werden — bitte Review prüfen."
            )

        # 8. In produktive bom schreiben
        cur.execute("""
            INSERT INTO bom (parent, child, qty, version_id, session_id)
            SELECT DISTINCT
                sb.parent_ref,
                sb.child_ref,
                sb.qty::int,
                sb.version_id,
                bv.session_id
            FROM staging_bom sb
            JOIN bom_version bv ON bv.id = sb.version_id
            JOIN staging_artikel sa_child
              ON sa_child.temp_ref    = sb.child_temp_ref
             AND sa_child.version_id  = sb.version_id
            WHERE sb.version_id = %s
              AND sa_child.match_status != 'ignorieren'
              AND sb.child_ref IS NOT NULL
            ON CONFLICT DO NOTHING
        """, (version_id,))

        # 9. Session auf freigegeben setzen
        cur.execute("""
            UPDATE bom_session bs
            SET status         = 'freigegeben',
                freigegeben_am = now()
            FROM bom_version bv
            WHERE bv.session_id = bs.id AND bv.id = %s
        """, (version_id,))

        return {
            "ok":           True,
            "version_id":   version_id,
            "neu_angelegt": neu_angelegt,
            "status":       "freigegeben",
        }

    except FreigabeFehler as e:
        return {"ok": False, "fehler": str(e)}

    finally:
        cur.close()