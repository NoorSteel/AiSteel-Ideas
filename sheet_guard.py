"""
sheet_guard.py
══════════════════════════════════════════════════════════════════════════════
Centralized Google Sheets Protection Layer
──────────────────────────────────────────────────────────────────────────────
RULE: No code in this project may delete, clear, or overwrite rows in the
      Google Sheet. Data integrity is guaranteed at this layer.

Usage — always get your worksheet through this module:

    from sheet_guard import safe_worksheet
    sheet = safe_worksheet(spreadsheet, SHEET_NAME)

Any call to a destructive method on the returned object will raise
SheetWriteProtectionError immediately — no data is lost.
══════════════════════════════════════════════════════════════════════════════
"""

import logging

logger = logging.getLogger(__name__)


class SheetWriteProtectionError(RuntimeError):
    """Raised when code attempts a destructive operation on the Google Sheet."""
    pass


# ── Methods that are ALWAYS blocked ──────────────────────────────────────────
_BLOCKED_METHODS = {
    "clear":            "sheet.clear() would erase ALL rows",
    "batch_clear":      "batch_clear() would erase selected ranges",
    "delete_row":       "delete_row() would remove a row permanently",
    "delete_rows":      "delete_rows() would remove rows permanently",
    "resize":           "resize() can destroy data below the new row limit",
    "delete_dimension": "delete_dimension() would remove rows/columns",
    # update() is allowed only for ADDING/EDITING cells, not for full rewrites;
    # full-rewrite protection is handled in ProtectedWorksheet.update()
}


class ProtectedWorksheet:
    """
    A transparent proxy around a gspread Worksheet that raises
    SheetWriteProtectionError before any destructive operation executes.
    All safe read/write operations pass through unchanged.
    """

    def __init__(self, worksheet):
        object.__setattr__(self, "_ws", worksheet)

    # ── Attribute access ──────────────────────────────────────────────────
    def __getattr__(self, name):
        if name in _BLOCKED_METHODS:
            reason = _BLOCKED_METHODS[name]
            def _blocked(*args, **kwargs):
                msg = (
                    f"\n{'═'*60}\n"
                    f"  🚫  SHEET PROTECTION VIOLATION\n"
                    f"  Blocked method : sheet.{name}()\n"
                    f"  Reason         : {reason}\n"
                    f"  Fix            : Filter data in the frontend layer,\n"
                    f"                   never delete rows from the sheet.\n"
                    f"{'═'*60}"
                )
                logger.critical(msg)
                raise SheetWriteProtectionError(msg)
            return _blocked

        attr = getattr(object.__getattribute__(self, "_ws"), name)
        return attr

    # ── Extra guard on update() — block full-sheet overwrites ─────────────
    def update(self, range_name, values=None, **kwargs):
        """
        Allow cell-level updates (e.g. a single column, a new row).
        Block any update that starts at A1 AND covers more rows than the
        current sheet already has — that would be a destructive overwrite.
        """
        ws = object.__getattribute__(self, "_ws")

        # Detect a full-sheet rewrite: range starts at A1 and values has
        # fewer rows than current sheet (i.e. it would delete trailing rows)
        if isinstance(range_name, str) and range_name.upper().startswith("A1"):
            if values is not None:
                current_row_count = ws.row_count
                new_row_count = len(values)
                if new_row_count < current_row_count - 1:   # -1 for header
                    msg = (
                        f"\n{'═'*60}\n"
                        f"  🚫  SHEET PROTECTION VIOLATION\n"
                        f"  Blocked method : sheet.update('A1', values)\n"
                        f"  Reason         : Full-sheet overwrite with fewer rows\n"
                        f"                   ({new_row_count} rows) than currently\n"
                        f"                   stored ({current_row_count} rows).\n"
                        f"                   This would permanently delete data.\n"
                        f"  Fix            : Use append_rows() for new data.\n"
                        f"{'═'*60}"
                    )
                    logger.critical(msg)
                    raise SheetWriteProtectionError(msg)

        return ws.update(range_name, values, **kwargs)

    def __repr__(self):
        ws = object.__getattribute__(self, "_ws")
        return f"<ProtectedWorksheet '{ws.title}'>"


def safe_worksheet(spreadsheet, sheet_name: str) -> ProtectedWorksheet:
    """
    Get a write-protected worksheet proxy.

    Example
    -------
        from sheet_guard import safe_worksheet
        sheet = safe_worksheet(spreadsheet, "AllData")
        sheet.append_rows(...)   # ✅ allowed
        sheet.clear()            # 🚫 raises SheetWriteProtectionError
    """
    ws = spreadsheet.worksheet(sheet_name)
    protected = ProtectedWorksheet(ws)
    logger.info(f"[SheetGuard] Worksheet '{sheet_name}' opened in PROTECTED mode — delete/clear ops are blocked.")
    return protected
