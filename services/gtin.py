def gs1_pruefziffer(basis: str) -> int:
    """Berechnet die GS1-13 Prüfziffer."""
    summe = sum(
        int(basis[i]) * (3 if i % 2 else 1)
        for i in range(12)
    )
    return (10 - (summe % 10)) % 10


def generiere_gtin(conn) -> int:
    """
    Gap-Filling GTIN — sucht die erste freie GTIN im GS1-Nummernraum.
    """
    with conn.cursor() as cur:
        # Alle vergebenen GTINs sortiert holen
        cur.execute("""
            SELECT gtin::bigint
            FROM product_master
            WHERE gtin IS NOT NULL
              AND gtin::text ~ '^[0-9]{13}$'
            ORDER BY gtin
        """)
        vergebene = [row[0] for row in cur.fetchall()]

    # Startwert
    basis_start = 4260000000001

    # Erste Lücke finden
    kandidat = basis_start
    vergebene_set = set(vergebene)

    while True:
        basis_str = str(kandidat).zfill(12)
        pruefziffer = gs1_pruefziffer(basis_str)
        gtin_kandidat = int(basis_str + str(pruefziffer))

        if gtin_kandidat not in vergebene_set:
            return gtin_kandidat

        kandidat += 1