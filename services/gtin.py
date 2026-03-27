# services/gtin.py

def generiere_gtin(conn) -> int:
    """
    Generiert die nächste GTIN-13 aus der Sequence seq_gtin13_basis.
    Prüfziffer wird automatisch berechnet via generate_next_gtin13().
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT generate_next_gtin13()")
        return cur.fetchone()[0]
    finally:
        cur.close()