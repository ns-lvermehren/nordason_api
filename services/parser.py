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
    is_existing:  bool = False
    polybag:      bool = False


def _is_internal_reference(ref: str) -> bool:
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
    if not val or not val.strip():
        return None
    return val.strip().capitalize()


def _is_polybag(val) -> bool:
    if val is None:
        return False
    return str(val).strip().upper() == 'X'


def parse_excel_bom(pfad: str) -> tuple[list[BOMNode], list[tuple]]:
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    ws = wb.worksheets[0]

    nodes: dict[str, BOMNode] = {}
    beziehungen: list[tuple] = []

    for row in ws.iter_rows(min_row=4, values_only=True):

        if not any(cell for cell in row if cell is not None):
            continue

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
        polybag       = _is_polybag(row[13]) if len(row) > 13 else False
        bemerkung     = _clean(row[14]) if len(row) > 14 else None

        if not item_ref:
            continue

        sub_type  = sub_type_raw  or 'Set'
        item_type = item_type_raw or 'Single'

        # Sub-Assembly Name generieren wenn nicht angegeben
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

        # Polybag + qty=1 → Sub-Ref ignorieren
        skip_sub = polybag and item_qty == 1.0

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
        if pkg_ref:
            if pkg_ref not in nodes:
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
        # Wenn polybag=True UND qty=1 → Sub-Ref ignorieren
        if sub_ref and not skip_sub:
            if sub_ref not in nodes:
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
        # Wenn polybag=True UND qty=1 → direkt dem Package zuordnen
        item_parent = pkg_ref if skip_sub else (sub_ref if sub_ref else pkg_ref)

        if item_ref:
            if item_ref not in nodes:
                nodes[item_ref] = BOMNode(
                    temp_ref=item_ref,
                    name=item_name or item_ref,
                    article_type=item_type,
                    parent_ref=item_parent,
                    qty=item_qty,
                    bemerkung=bemerkung,
                    is_existing=_is_internal_reference(item_ref),
                    polybag=polybag,
                )
            if item_parent:
                beziehungen.append((item_parent, item_ref, item_qty))

    wb.close()
    return list(nodes.values()), beziehungen