import openpyxl
from dataclasses import dataclass
from typing import Optional


@dataclass
class RohZeile:
    zeile_nr:    int
    ebene:       int
    bezeichnung: str
    menge:       Optional[float]
    einheit:     str
    article_type: str
    parent_idx:  Optional[int] = None


def parse_excel_bom(
    pfad: str,
    ebenen_spalten: list[int],
    menge_spalte: int,
    einheit_spalte: int,
    artikeltyp_spalte: int,
    startzeile: int = 2,
) -> list[RohZeile]:
    """
    Liest Excel-BOM mit einer Spalte pro Hierarchieebene.
    Gibt flache Liste mit parent_idx zurück.
    """
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    ws = wb.active
    zeilen: list[RohZeile] = []
    ebenen_stack: dict[int, int] = {}

    for row_idx, row in enumerate(
        ws.iter_rows(min_row=startzeile, values_only=True), start=startzeile
    ):
        aktive_ebene = None
        bezeichnung = None

        for ebene, col_idx in enumerate(ebenen_spalten):
            wert = row[col_idx]
            if wert is not None and str(wert).strip():
                aktive_ebene = ebene
                bezeichnung = str(wert).strip()
                break

        if aktive_ebene is None:
            continue

        try:
            menge_raw = row[menge_spalte]
            menge = float(str(menge_raw).replace(',', '.').strip()) \
                    if menge_raw else None
        except ValueError:
            menge = None

        einheit     = str(row[einheit_spalte]).strip() \
                      if row[einheit_spalte] else 'Stk'
        article_type = str(row[artikeltyp_spalte]).strip().lower() \
                      if row[artikeltyp_spalte] else 'single'

        parent_idx = ebenen_stack.get(aktive_ebene - 1) \
                     if aktive_ebene > 0 else None

        zeile = RohZeile(
            zeile_nr=row_idx,
            ebene=aktive_ebene,
            bezeichnung=bezeichnung,
            menge=menge,
            einheit=einheit,
            article_type=article_type,
            parent_idx=parent_idx,
        )

        ebenen_stack[aktive_ebene] = len(zeilen)
        for e in list(ebenen_stack.keys()):
            if e > aktive_ebene:
                del ebenen_stack[e]

        zeilen.append(zeile)

    wb.close()
    return zeilen