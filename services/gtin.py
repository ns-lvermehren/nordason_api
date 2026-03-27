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


def berechne_gtin14_aus_gtin13(gtin13: int) -> int:
    """
    Berechnet GTIN-14 aus GTIN-13 nach GS1 Modulo-10.
    Prefix '1' vorne, erste 12 Stellen der GTIN-13, neue Prüfziffer.
    """
    s = str(gtin13)
    basis = '1' + s[:12]  # 13 Stellen
    total = 0
    for i, digit in enumerate(basis):
        if (len(basis) - i) % 2 == 0:
            factor = 1
        else:
            factor = 3
        total += int(digit) * factor
    check = (10 - (total % 10)) % 10
    return int(basis + str(check))