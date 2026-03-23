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
    unit:         str = 'Stk'
    gtin:         Optional[str] = None
    bemerkung:    Optional[str] = None
    is_existing:  bool = False   # True wenn item_ref eine internal_reference ist


def _is_internal_reference(ref: str) -> bool:
    """
    Prüft ob eine Referenz bereits eine internal_reference ist
    (numerisch) oder eine temp_id (alphanumerisch wie S001, P001).
    """
    if ref is None:
        return False
    try:
        int(ref)
        return True   # rein numerisch → internal_reference
    except ValueError:
        return False  # alphanumerisch → temp_id


def parse_excel_bom(pfad: str) -> tuple[list[BOMNode], list[tuple]]:
    """
    Parst die Nordason BOM-Vorlage.

    Spalten (0-basiert):
      0  set_ref           Ebene 1 Referenz
      1  set_name          Ebene 1 Name
      2  package_ref       Ebene 2 Referenz
      3  package_name      Ebene 2 Name
      4  package_qty       Menge Ebene 2 in Ebene 1
      5  sub_ref           Ebene 3 Referenz (optional)
      6  sub_name          Ebene 3 Name
      7  sub_qty           Menge Ebene 3 in Ebene 2
      8  sub_article_type  Artikeltyp Ebene 3
      9  item_ref          Ebene 4 Referenz
      10 item_name         Ebene 4 Name
      11 item_qty          Menge Ebene 4
      12 item_article_type Artikeltyp Ebene 4
      13 item_gtin         GTIN (optional)
      14 bemerkung         Notiz

    Gibt zurück:
      nodes        — alle eindeutigen Knoten
      beziehungen  — (parent_ref, child_ref, qty) Tupel
    """
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    ws = wb.active

    nodes: dict[str, BOMNode] = {}
    beziehungen: list[tuple] = []

    for row in ws.iter_rows(min_row=3, values_only=True):  # ab Zeile 3 (nach Header + Beschreibung)

        # Zeile leer → überspringen
        if not any(row):
            continue

        # Werte extrahieren
        set_ref    = str(row[0]).strip() if row[0] else None
        set_name   = str(row[1]).strip() if row[1] else None
        pkg_ref    = str(row[2]).strip() if row[2] else None
        pkg_name   = str(row[3]).strip() if row[3] else None
        pkg_qty    = _parse_qty(row[4])
        sub_ref    = str(row[5]).strip() if row[5] else None
        sub_name   = str(row[6]).strip() if row[6] else None
        sub_qty    = _parse_qty(row[7])
        sub_type   = str(row[8]).strip() if row[8] else 'Set'
        item_ref   = str(row[9]).strip() if row[9] else None
        item_name  = str(row[10]).strip() if row[10] else None
        item_qty   = _parse_qty(row[11])
        item_type  = str(row[12]).strip() if row[12] else 'Single'
        item_gtin  = str(row[13]).strip() if row[13] else None
        bemerkung  = str(row[14]).strip() if row[14] else None

        # ── Ebene 1: Set ─────────────────────────────────────
        if set_ref and set_ref not in nodes:
            nodes[set_ref] = BOMNode(
                temp_ref=set_ref,
                name=set_name or set_ref,
                article_type='Set',
                parent_ref=None,
                qty=1,
                is_existing=_is_internal_reference(set_ref),
            )

        # ── Ebene 2: Package ─────────────────────────────────
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

        # ── Ebene 3: Sub-Assembly (optional) ─────────────────
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
        # Parent ist sub_ref wenn vorhanden, sonst pkg_ref
        item_parent = sub_ref if sub_ref else pkg_ref

        if item_ref and item_ref not in nodes:
            nodes[item_ref] = BOMNode(
                temp_ref=item_ref,
                name=item_name or item_ref,
                article_type=item_type,
                parent_ref=item_parent,
                qty=item_qty,
                gtin=item_gtin,
                bemerkung=bemerkung,
                is_existing=_is_internal_reference(item_ref),
            )
            if item_parent:
                beziehungen.append((item_parent, item_ref, item_qty))

    wb.close()
    return list(nodes.values()), beziehungen


def _parse_qty(val) -> float:
    if val is None:
        return 1.0
    try:
        return float(str(val).replace(',', '.').strip())
    except ValueError:
        return 1.0