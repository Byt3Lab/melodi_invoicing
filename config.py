from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_invoicing"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)


class MelodiInvoicingTables(BaseModuleTables):
    INVOICES = "m_invoicing_invoices"
    INVOICE_LINES = "m_invoicing_invoice_lines"