from core.module import ApplicationModule, Permission
from core.routing import Router
from modules.melodi_invoicing.controllers.api import InvoicingAPIController
from modules.melodi_invoicing.controllers.web import InvoicingWebController

class InvoicingModule(ApplicationModule):
    def _get_permissions(self):
        return [
            Permission(self, "invoicing:read", "Consulter les factures"),
            Permission(self, "invoicing:write", "Gérer les factures (Créer, valider, payer)")
        ]

    async def load(self):
        """
        Initialisation du module de facturation
        """
        self.permissions = self._get_permissions()

        # Exécution des migrations de base de données pour ce module (dev mode)
        if self.app.server.app.debug:
            await self.run_dev_migrations()

        # Enregistrement des routes API
        self.api_router.add_route("/pdf/<invoice_id>", InvoicingAPIController.get_invoice_pdf, methods=["GET"])
        
        # Enregistrement de la route publique /verify
        verify_router = Router(id="invoicing_verify", module=self)
        verify_router.add_route("/<invoice_id>", InvoicingAPIController.verify_invoice, methods=["GET"])
        self.app.public_router.add_router(verify_router, url_prefix="/verify")
        
        # Enregistrement des routes web d'administration
        self.admin_router.add_route("", InvoicingWebController.admin_dashboard, methods=["GET"])
        self.admin_router.add_route("/", InvoicingWebController.admin_dashboard, methods=["GET"])

        self.admin_router.add_route("/invoices", InvoicingWebController.admin_invoices, methods=["GET"])
        self.admin_router.add_route("/invoices/create", InvoicingWebController.admin_create_invoice, methods=["GET", "POST"])
        self.admin_router.add_route("/invoices/view", InvoicingWebController.admin_view_invoice, methods=["GET"])
        self.admin_router.add_route("/invoices/validate", InvoicingWebController.admin_validate_invoice, methods=["POST"])
        self.admin_router.add_route("/invoices/pay", InvoicingWebController.admin_register_payment, methods=["POST"])

        # Enregistrement de la navigation dans l'ERP
        self.register_navigation(
            id="invoicing_root",
            label="Facturation",
            icon="name=receipt&fill=white",
            url="/admin/melodi_invoicing",
            priority=80,
            children=[
                {"label": "Tableau de Bord", "icon": "name=dashboard&fill=white", "url": "/admin/melodi_invoicing"},
                {"label": "Factures", "icon": "name=receipt_long&fill=white", "url": "/admin/melodi_invoicing/invoices"},
                {"label": "Créer une Facture", "icon": "name=add&fill=white", "url": "/admin/melodi_invoicing/invoices/create"}
            ]
        )

        # Enregistrement des actions et écouteurs d'événements inter-modules
        self.register_inter_module_handlers()

    def register_inter_module_handlers(self):
        # Actions enregistrées pour exécution synchrone via execute_action("melodi_invoicing", action_name, payload)
        self.add_action("create_invoice", self.handle_create_invoice)
        self.add_action("add_line", self.handle_add_invoice_line)
        self.add_action("update_line", self.handle_update_invoice_line)
        self.add_action("delete_line", self.handle_delete_invoice_line)

        # Event Listeners enregistrés pour écouter les événements émis vers melodi_invoicing
        self.app.hook_manager.event_listener.add("melodi_invoicing", "create_invoice", self.handle_create_invoice)
        self.app.hook_manager.event_listener.add("melodi_invoicing", "add_line", self.handle_add_invoice_line)
        self.app.hook_manager.event_listener.add("melodi_invoicing", "update_line", self.handle_update_invoice_line)
        self.app.hook_manager.event_listener.add("melodi_invoicing", "delete_line", self.handle_delete_invoice_line)

    async def handle_create_invoice(self, payload: dict) -> dict:
        from modules.melodi_invoicing.services.services import InvoicingService
        async with self.app.db.get_session() as session:
            invoice = await InvoicingService.create_invoice(
                session=session,
                branch_id=payload.get("branch_id"),
                contact_id=payload.get("contact_id"),
                invoice_type=payload.get("invoice_type", "IN_CUSTOMER"),
                origin_module=payload.get("origin_module"),
                origin_reference=payload.get("origin_reference"),
                created_by_user_id=payload.get("created_by_user_id"),
                lines=payload.get("lines")
            )
            await session.commit()
            return {"status": "success", "invoice_id": invoice.invoice_id, "invoice_number": invoice.invoice_number}

    async def handle_add_invoice_line(self, payload: dict) -> dict:
        from modules.melodi_invoicing.services.services import InvoicingService
        async with self.app.db.get_session() as session:
            line = await InvoicingService.add_invoice_line(
                session=session,
                invoice_id=payload.get("invoice_id"),
                description=payload.get("description", "Ligne de facture"),
                quantity=payload.get("quantity", 1),
                unit_price=payload.get("unit_price", 0),
                tax_rate=payload.get("tax_rate", 0),
                origin_module=payload.get("origin_module"),
                origin_reference=payload.get("origin_reference")
            )
            await session.commit()
            return {"status": "success", "line_id": line.line_id, "subtotal": float(line.subtotal)}

    async def handle_update_invoice_line(self, payload: dict) -> dict:
        from modules.melodi_invoicing.services.services import InvoicingService
        async with self.app.db.get_session() as session:
            line = await InvoicingService.update_invoice_line(
                session=session,
                line_id=payload.get("line_id"),
                requesting_module=payload.get("origin_module") or payload.get("requesting_module"),
                description=payload.get("description"),
                quantity=payload.get("quantity"),
                unit_price=payload.get("unit_price"),
                tax_rate=payload.get("tax_rate")
            )
            await session.commit()
            return {"status": "success", "line_id": line.line_id, "subtotal": float(line.subtotal)}

    async def handle_delete_invoice_line(self, payload: dict) -> dict:
        from modules.melodi_invoicing.services.services import InvoicingService
        async with self.app.db.get_session() as session:
            await InvoicingService.delete_invoice_line(
                session=session,
                line_id=payload.get("line_id"),
                requesting_module=payload.get("origin_module") or payload.get("requesting_module")
            )
            await session.commit()
            return {"status": "success", "deleted": True}

    async def run_dev_migrations(self):
        from modules.melodi_invoicing.models.models import InvoiceModel, InvoiceLineModel
        from modules.melodi_invoicing.config import MelodiInvoicingTables
        await self.app.db.create_all([InvoiceModel, InvoiceLineModel])
        
        # Alter table for new origin_module & origin_reference columns if not present
        inv_table = MelodiInvoicingTables.INVOICES
        lines_table = MelodiInvoicingTables.INVOICE_LINES
        
        queries = [
            f"ALTER TABLE {inv_table} ADD COLUMN IF NOT EXISTS origin_module VARCHAR(100);",
            f"ALTER TABLE {inv_table} ADD COLUMN IF NOT EXISTS origin_reference VARCHAR(100);",
            f"ALTER TABLE {lines_table} ADD COLUMN IF NOT EXISTS origin_module VARCHAR(100);",
            f"ALTER TABLE {lines_table} ADD COLUMN IF NOT EXISTS origin_reference VARCHAR(100);"
        ]
        for q in queries:
            try:
                await self.app.db.execute(q, query_type="write")
            except Exception as e:
                print(f"[melodi_invoicing] Migration query failed: {q} -> {e}")

module = InvoicingModule(
    name="melodi_invoicing", 
    router_name="melodi_invoicing"
)
