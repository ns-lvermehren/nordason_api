def generiere_artikelnummer(conn, article_type: str) -> str:
    """
    Holt den nächsten Wert aus der Sequence für diesen Artikeltyp.
    Atomar, kein Race Condition möglich.
    """
    seq_name = f"seq_artno_{article_type.lower().replace(' ', '_')}"

    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_sequences
                WHERE schemaname = 'public'
                  AND sequencename = %s
            )
        """, (seq_name,))

        if not cur.fetchone()[0]:
            raise ValueError(
                f"Kein Nummernkreis für Artikeltyp '{article_type}'. "
                f"Bitte in product_type eintragen."
            )

        cur.execute(f"SELECT nextval('{seq_name}')")
        return str(cur.fetchone()[0])