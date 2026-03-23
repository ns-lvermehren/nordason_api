# services/parser.py
import openpyxl
from dataclasses import dataclass
from typing import Optional


@dataclass
class BOMNode:
    temp_ref:     str
    name:         str
    article_type: str
    parent_ref:   Optional[str]
    qty:          float
    bemerkung:    Optional[str] = None
    is_existing:  bool = False  # True wenn item_ref numerisch = internal_reference


def _is_internal_reference(ref: str) -> bool:
    """
    Numerisch → bereits in product_master (internal_reference).
    Alphanumerisch (S001, P001) → temp_id, neuer Artikel.
    """
    if not ref:
        return False
    try:
        int(ref)
        return True
    except ValueError:
        return False


def _parse_qty(val) -> float:
    if val is None:
        return 1.0
    try:
        return float(str(val).replace(',', '.').strip())
    except ValueError:
        return 1.0


def _clean(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _normalize_article_type(val: Optional[str]) -> Optional[str]:
    """
    Ersten Buchstaben groß, Rest klein.
    Gibt None zurück wenn leer.
    """
    if not val or not val.strip():
        return None
    return val.strip().capitalize()


def parse_excel_bom(pfad: str) -> tuple[list[BOMNode], list[tuple]]:
    """
    Parst die Nordason BOM-Vorlage.

    Nimmt immer das erste Sheet.

    Zeile 1: Spaltenheader     (übersprungen)
    Zeile 2: Beschreibungszeile (übersprungen)
    Ab Zeile 3: Daten

    Spalten (0-basiert):
      0  set_ref            Ebene 1 Referenz
      1  set_name           Ebene 1 Name
      2  package_ref        Ebene 2 Referenz
      3  package_name       Ebene 2 Name
      4  package_qty        Menge Ebene 2 in Ebene 1
      5  sub_ref            Ebene 3 Referenz (optional)
      6  sub_name           Ebene 3 Name (automatisch per Formel)
      7  sub_qty            Menge Ebene 3 in Ebene 2
      8  sub_article_type   Artikeltyp Ebene 3
      9  item_ref           Ebene 4 Referenz
      10 item_name          Ebene 4 Name
      11 item_qty           Menge Ebene 4
      12 item_article_type  Artikeltyp Ebene 4
      13 bemerkung          Interne Notiz

    Artikeltypen:
      Ebene 1 → immer 'Set'
      Ebene 2 → immer 'Set'
      Ebene 3 → aus Spalte 8, Fallback 'Set'
      Ebene 4 → aus Spalte 12, Fallback 'Single'

    Gibt zurück:
      nodes        — Liste aller eindeutigen BOMNode Objekte
      beziehungen  — Liste von (parent_ref, child_ref, qty) Tupeln
    """
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)

    # Immer erstes Sheet
    ws = wb.worksheets[0]

    nodes: dict[str, BOMNode] = {}
    beziehungen: list[tuple] = []

    for row in ws.iter_rows(min_row=3, values_only=True):

        # Komplett leere Zeile überspringen
        if not any(cell for cell in row if cell is not None):
            continue

        # ── Werte einlesen ────────────────────────────────────
        set_ref       = _clean(row[0])
        set_name      = _clean(row[1])
        pkg_ref       = _clean(row[2])
        pkg_name      = _clean(row[3])
        pkg_qty       = _parse_qty(row[4])
        sub_ref       = _clean(row[5])
        sub_name_raw  = _clean(row[6])
        sub_qty       = _parse_qty(row[7])
        sub_type_raw  = _normalize_article_type(_clean(row[8]))
        item_ref      = _clean(row[9])
        item_name     = _clean(row[10])
        item_qty      = _parse_qty(row[11])
        item_type_raw = _normalize_article_type(_clean(row[12]))
        bemerkung     = _clean(row[13])

        # Mindestanforderung
        if not item_ref:
            continue

        # ── article_type Auflösung ────────────────────────────
        sub_type  = sub_type_raw  or 'Set'
        item_type = item_type_raw or 'Single'

        # ── sub_name berechnen ────────────────────────────────
        # Aus Excel-Formel übernehmen oder selbst berechnen
        if sub_ref:
            if sub_name_raw and sub_name_raw != sub_ref:
                sub_name = sub_name_raw
            else:
                qty_str  = str(int(item_qty)) \
                           if item_qty == int(item_qty) else str(item_qty)
                sub_name = f"Polybag | {qty_str}x {item_name}" \
                           if item_name else f"Polybag | {sub_ref}"
        else:
            sub_name = None

        # ── Ebene 1: Set ──────────────────────────────────────
        if set_ref and set_ref not in nodes:
            nodes[set_ref] = BOMNode(
                temp_ref=set_ref,
                name=set_name or set_ref,
                article_type='Set',
                parent_ref=None,
                qty=1,
                is_existing=_is_internal_reference(set_ref),
            )

        # ── Ebene 2: Package ──────────────────────────────────
        if pkg_ref and pkg_ref not in nodes:
            nodes[pkg_ref] = BOMNode(
                temp_ref=pkg_ref,
                name=pkg_name or pkg_ref,
                article_type='Set',
                parent_ref=set_ref,
                qty=pkg_qty,
                is_existing=_is_internal_reference(pkg_ref),
            )
            if set_ref:
                beziehungen.append((set_ref, pkg_ref, pkg_qty))

        # ── Ebene 3: Sub-Assembly (optional) ──────────────────
        if sub_ref and sub_ref not in nodes:
            nodes[sub_ref] = BOMNode(
                temp_ref=sub_ref,
                name=sub_name or sub_ref,
                article_type=sub_type,
                parent_ref=pkg_ref,
                qty=sub_qty,
                is_existing=_is_internal_reference(sub_ref),
            )
            if pkg_ref:
                beziehungen.append((pkg_ref, sub_ref, sub_qty))

        # ── Ebene 4: Einzelartikel ────────────────────────────
        # Parent = sub_ref wenn vorhanden, sonst pkg_ref
        item_parent = sub_ref if sub_ref else pkg_ref

        if item_ref and item_ref not in nodes:
            nodes[item_ref] = BOMNode(
                temp_ref=item_ref,
                name=item_name or item_ref,
                article_type=item_type,
                parent_ref=item_parent,
                qty=item_qty,
                bemerkung=bemerkung,
                is_existing=_is_internal_reference(item_ref),
            )
            if item_parent:
                beziehungen.append((item_parent, item_ref, item_qty))

    wb.close()
    return list(nodes.values()), beziehungen