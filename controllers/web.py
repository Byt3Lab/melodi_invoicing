import json
import uuid
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from core.routing import Request, Response
from core.page_builder import Page, Component
from base.components import admin_layout

from base.models.contact_model import ContactModel
from base.models.branch_model import BranchModel
from base.models.currency_model import CurrencyModel
from modules.melodi_treasury.models.models import TreasuryJournalModel

from modules.melodi_invoicing.models.models import InvoiceModel, InvoiceLineModel, InvoiceStatus, InvoiceType
from modules.melodi_invoicing.services.services import InvoicingService


class InvoicingWebController:

    @classmethod
    def get_user_payload(cls, request: Request) -> dict:
        """
        Safely retrieves the user payload from the session.
        """
        user_raw = request.get_session("user_payload")
        if not user_raw:
            return {}
        try:
            return json.loads(user_raw) if isinstance(user_raw, str) else user_raw
        except Exception:
            return {}

    @classmethod
    async def admin_invoices(cls, request: Request, response: Response):
        """
        Affiche la liste des factures.
        """
        search_query = request.query.get("search", "")
        status_filter = request.query.get("status", "")

        user_payload = cls.get_user_payload(request)
        active_branch_id = user_payload.get("active_branch")

        if not active_branch_id:
            return response.redirect("/admin?error=Aucune+agence+active")

        async with request.module.app.db.get_session() as session:
            stmt = select(InvoiceModel).order_by(InvoiceModel.created_at.desc())
            if active_branch_id:
                stmt = stmt.where(InvoiceModel.branch_id == active_branch_id)
            if status_filter:
                stmt = stmt.where(InvoiceModel.status == InvoiceStatus(status_filter))

            stmt = stmt.options(selectinload(InvoiceModel.lines))
            res = await session.execute(stmt)
            invoices = res.scalars().all()

            # Enrichir avec les contacts
            for inv in invoices:
                c_stmt = select(ContactModel).where(ContactModel.contact_id == inv.contact_id)
                c_res = await session.execute(c_stmt)
                inv.contact = c_res.scalar()

        content = Component(
            module_name="melodi_invoicing",
            name="admin_invoices",
            context={
                "invoices": invoices,
                "search_query": search_query,
                "status_filter": status_filter,
                "InvoiceStatus": InvoiceStatus
            }
        )
        page = Page("Gestion des Factures", admin_layout(content))
        return await response.render_page(page)

    @classmethod
    async def admin_view_invoice(cls, request: Request, response: Response):
        """
        Affiche les détails d'une facture.
        """
        invoice_id = request.query.get("invoice_id")
        if not invoice_id:
            return response.redirect("/admin/melodi_invoicing/invoices")

        async with request.module.app.db.get_session() as session:
            stmt = (
                select(InvoiceModel)
                .where(InvoiceModel.invoice_id == invoice_id)
                .options(selectinload(InvoiceModel.lines))
            )
            res = await session.execute(stmt)
            invoice = res.scalar_one_or_none()

            if not invoice:
                return response.redirect("/admin/melodi_invoicing/invoices?error=Facture+introuvable")

            # Contact
            c_stmt = select(ContactModel).where(ContactModel.contact_id == invoice.contact_id)
            c_res = await session.execute(c_stmt)
            invoice.contact = c_res.scalar()

            # Treasury journals
            journals = []
            if invoice.status in [InvoiceStatus.VALIDATED, InvoiceStatus.PARTIALLY_PAID]:
                j_stmt = select(TreasuryJournalModel).where(
                    TreasuryJournalModel.branch_id == invoice.branch_id,
                    TreasuryJournalModel.is_active == True
                )
                j_res = await session.execute(j_stmt)
                journals = j_res.scalars().all()

        content = Component(
            module_name="melodi_invoicing",
            name="admin_view_invoice",
            context={
                "invoice": invoice,
                "journals": journals,
                "InvoiceStatus": InvoiceStatus
            }
        )
        page = Page(f"Facture {invoice.invoice_number or '(Brouillon)'}", admin_layout(content))
        return await response.render_page(page)

    @classmethod
    async def admin_create_invoice(cls, request: Request, response: Response):
        """
        Création d'une nouvelle facture via formulaire (GET/POST).
        """
        user_payload = cls.get_user_payload(request)
        active_branch_id = user_payload.get("active_branch")
        user_id = user_payload.get("user_id")

        if not active_branch_id:
            return response.redirect("/admin/melodi_invoicing/invoices?error=Aucune+agence+active")

        if request.method == "POST":
            form = request.form

            contact_id = form.get("contact_id")
            invoice_type_str = form.get("invoice_type", "IN_CUSTOMER")

            labels = form.getlist("label[]")
            quantities = form.getlist("quantity[]")
            unit_prices = form.getlist("unit_price[]")
            tax_rates = form.getlist("tax_rate[]")

            if not contact_id or not labels:
                return response.redirect("/admin/melodi_invoicing/invoices/create?error=Informations+incompletes")

            try:
                invoice_id = str(uuid.uuid4())
                async with request.module.app.db.get_session() as session:
                    new_invoice = InvoiceModel(
                        invoice_id=invoice_id,
                        branch_id=active_branch_id,
                        contact_id=contact_id,
                        invoice_type=InvoiceType(invoice_type_str),
                        status=InvoiceStatus.DRAFT,
                        created_by_user_id=user_id
                    )
                    session.add(new_invoice)

                    for i in range(len(labels)):
                        qty = Decimal(quantities[i])
                        price = Decimal(unit_prices[i])
                        tax = Decimal(tax_rates[i]) / Decimal("100.0000")
                        subtotal = qty * price
                        line_total = subtotal + (subtotal * tax)

                        line = InvoiceLineModel(
                            line_id=str(uuid.uuid4()),
                            invoice_id=invoice_id,
                            description=labels[i],
                            quantity=qty,
                            unit_price=price,
                            tax_rate=tax,
                            subtotal=line_total
                        )
                        session.add(line)

                    await session.flush()
                    await InvoicingService.calculate_invoice_totals(session, invoice_id)
                    await session.commit()

                return response.redirect(f"/admin/melodi_invoicing/invoices/view?invoice_id={invoice_id}")
            except Exception as e:
                return response.redirect(f"/admin/melodi_invoicing/invoices/create?error={str(e)}")

        async with request.module.app.db.get_session() as session:
            c_stmt = select(ContactModel).order_by(ContactModel.company_name, ContactModel.last_name)
            c_res = await session.execute(c_stmt)
            contacts = c_res.scalars().all()

            cur_stmt = select(CurrencyModel).order_by(CurrencyModel.code)
            cur_res = await session.execute(cur_stmt)
            currencies = cur_res.scalars().all()

        content = Component(
            module_name="melodi_invoicing",
            name="admin_create_invoice",
            context={
                "contacts": contacts,
                "currencies": currencies,
                "InvoiceType": InvoiceType
            }
        )
        page = Page("Nouvelle Facture", admin_layout(content))
        return await response.render_page(page)

    @classmethod
    async def admin_validate_invoice(cls, request: Request, response: Response):
        """
        Action pour valider la facture (POST).
        """
        if request.method == "POST":
            form = request.form
            invoice_id = form.get("invoice_id")

            try:
                async with request.module.app.db.get_session() as session:
                    await InvoicingService.validate_invoice(session, invoice_id)
                    await session.commit()
                return response.redirect(f"/admin/melodi_invoicing/invoices/view?invoice_id={invoice_id}")
            except Exception as e:
                return response.redirect(f"/admin/melodi_invoicing/invoices/view?invoice_id={invoice_id}&error={str(e)}")

        return response.redirect("/admin/melodi_invoicing/invoices")

    @classmethod
    async def admin_register_payment(cls, request: Request, response: Response):
        """
        Action pour enregistrer un paiement (POST).
        """
        if request.method == "POST":
            form = request.form
            invoice_id = form.get("invoice_id")
            journal_id = form.get("journal_id")
            amount = Decimal(form.get("amount", "0"))
            exchange_rate = Decimal(form.get("exchange_rate", "1.0000"))

            user_payload = cls.get_user_payload(request)
            user_id = user_payload.get("user_id")

            try:
                async with request.module.app.db.get_session() as session:
                    await InvoicingService.register_invoice_payment(
                        session=session,
                        invoice_id=invoice_id,
                        journal_id=journal_id,
                        amount=amount,
                        created_by_user_id=user_id,
                        exchange_rate=exchange_rate
                    )
                    await session.commit()
                return response.redirect(f"/admin/melodi_invoicing/invoices/view?invoice_id={invoice_id}")
            except Exception as e:
                return response.redirect(f"/admin/melodi_invoicing/invoices/view?invoice_id={invoice_id}&error={str(e)}")

        return response.redirect("/admin/melodi_invoicing/invoices")

    @classmethod
    async def admin_dashboard(cls, request: Request, response: Response):
        """
        Main Admin Dashboard page for MELODI Invoicing (/admin/melodi_invoicing).
        Provides an overview of invoices, total amounts, collection stats, and recent invoices.
        """
        user_payload = cls.get_user_payload(request)
        active_branch_id = user_payload.get("active_branch")

        if not active_branch_id:
            return response.redirect("/admin?error=Aucune+agence+active")

        async with request.module.app.db.get_session() as session:
            stmt = select(InvoiceModel).order_by(InvoiceModel.created_at.desc())
            if active_branch_id:
                stmt = stmt.where(InvoiceModel.branch_id == active_branch_id)

            stmt = stmt.options(selectinload(InvoiceModel.lines))
            res = await session.execute(stmt)
            all_invoices = list(res.scalars().all())

            # Enrich with contacts
            for inv in all_invoices:
                c_stmt = select(ContactModel).where(ContactModel.contact_id == inv.contact_id)
                c_res = await session.execute(c_stmt)
                inv.contact = c_res.scalar()

            total_invoiced = sum((inv.total_amount for inv in all_invoices), Decimal("0.0000"))
            total_paid = sum((inv.amount_paid for inv in all_invoices), Decimal("0.0000"))
            total_unpaid = total_invoiced - total_paid

            stats = {
                "total_count": len(all_invoices),
                "total_invoiced": total_invoiced,
                "total_paid": total_paid,
                "total_unpaid": total_unpaid,
                "draft_count": sum(1 for inv in all_invoices if inv.status == InvoiceStatus.DRAFT),
                "validated_count": sum(1 for inv in all_invoices if inv.status == InvoiceStatus.VALIDATED),
                "partially_paid_count": sum(1 for inv in all_invoices if inv.status == InvoiceStatus.PARTIALLY_PAID),
                "paid_count": sum(1 for inv in all_invoices if inv.status == InvoiceStatus.PAID),
                "cancelled_count": sum(1 for inv in all_invoices if inv.status == InvoiceStatus.CANCELLED),
                "customer_count": sum(1 for inv in all_invoices if inv.invoice_type == InvoiceType.IN_CUSTOMER),
                "vendor_count": sum(1 for inv in all_invoices if inv.invoice_type == InvoiceType.OUT_VENDOR),
            }

            recent_invoices = all_invoices[:5]

        content = Component(
            module_name="melodi_invoicing",
            name="admin_dashboard",
            context={
                "stats": stats,
                "recent_invoices": recent_invoices,
                "InvoiceStatus": InvoiceStatus,
                "InvoiceType": InvoiceType
            }
        )
        page = Page("Tableau de bord Facturation", admin_layout(content))
        return await response.render_page(page)
