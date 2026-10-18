import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from modules.melodi_invoicing.models.models import InvoiceModel, InvoiceLineModel, InvoiceStatus, InvoiceType
from modules.melodi_treasury.services.services import TreasuryService
from modules.melodi_treasury.models.models import TransactionDirection, TransactionSource


class InvoicingService:

    @staticmethod
    async def calculate_invoice_totals(session: AsyncSession, invoice_id: str) -> InvoiceModel:
        """
        Calculates and updates subtotal for lines and total_amount for the invoice.
        """
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.invoice_id == invoice_id)
            .options(selectinload(InvoiceModel.lines))
        )
        res = await session.execute(stmt)
        invoice = res.scalar_one_or_none()

        if not invoice:
            raise ValueError(f"Invoice with ID {invoice_id} not found.")

        total_amount = Decimal("0.0000")
        for line in invoice.lines:
            subtotal = line.quantity * line.unit_price
            tax_amount = subtotal * line.tax_rate
            line.subtotal = subtotal + tax_amount
            total_amount += line.subtotal

        invoice.total_amount = total_amount
        await session.flush()
        return invoice

    @staticmethod
    async def validate_invoice(session: AsyncSession, invoice_id: str) -> InvoiceModel:
        """
        Validates a draft invoice, generating a sequential invoice number.
        """
        # Lock invoice for update
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.invoice_id == invoice_id)
            .options(selectinload(InvoiceModel.lines))
            .with_for_update()
        )
        res = await session.execute(stmt)
        invoice = res.scalar_one_or_none()

        if not invoice:
            raise ValueError("Invoice not found.")

        if invoice.status != InvoiceStatus.DRAFT:
            raise ValueError("Only draft invoices can be validated.")

        # Recalculate totals before validation
        total_amount = Decimal("0.0000")
        for line in invoice.lines:
            subtotal = line.quantity * line.unit_price
            tax_amount = subtotal * line.tax_rate
            line.subtotal = subtotal + tax_amount
            total_amount += line.subtotal
        invoice.total_amount = total_amount

        # Generate official sequence number
        year = datetime.utcnow().year
        prefix = f"INV-{year}-" if invoice.invoice_type == InvoiceType.IN_CUSTOMER else f"BILL-{year}-"

        # Search for the highest sequence number of this pattern
        seq_stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.invoice_number.like(f"{prefix}%"))
            .order_by(InvoiceModel.invoice_number.desc())
            .with_for_update()
        )
        seq_res = await session.execute(seq_stmt)
        last_invoice = seq_res.scalars().first()

        next_seq = 1
        if last_invoice and last_invoice.invoice_number:
            try:
                last_seq_str = last_invoice.invoice_number.split("-")[-1]
                next_seq = int(last_seq_str) + 1
            except Exception:
                pass

        invoice.invoice_number = f"{prefix}{next_seq:04d}"
        invoice.status = InvoiceStatus.VALIDATED
        invoice.updated_at = datetime.utcnow()

        await session.flush()
        return invoice

    @staticmethod
    async def register_invoice_payment(
        session: AsyncSession,
        invoice_id: str,
        journal_id: str,
        amount: Decimal | float | str,
        created_by_user_id: str,
        exchange_rate: Decimal | float | str = Decimal("1.0000")
    ) -> InvoiceModel:
        """
        Registers a payment against an invoice and creates a corresponding treasury transaction.
        """
        amount_dec = Decimal(str(amount))
        rate_dec = Decimal(str(exchange_rate))

        # Lock invoice for update
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.invoice_id == invoice_id)
            .with_for_update()
        )
        res = await session.execute(stmt)
        invoice = res.scalar_one_or_none()

        if not invoice:
            raise ValueError("Invoice not found.")

        if invoice.status not in [InvoiceStatus.VALIDATED, InvoiceStatus.PARTIALLY_PAID]:
            raise ValueError("Payment can only be registered on validated or partially paid invoices.")

        remaining = invoice.total_amount - invoice.amount_paid
        if amount_dec > remaining:
            raise ValueError(f"Payment amount ({amount_dec}) exceeds remaining balance ({remaining}).")

        # Determine transaction params based on invoice type
        if invoice.invoice_type == InvoiceType.IN_CUSTOMER:
            direction = TransactionDirection.IN
            source_type = TransactionSource.CUSTOMER_INVOICE
            description = f"Payment for invoice {invoice.invoice_number}"
        elif invoice.invoice_type == InvoiceType.OUT_VENDOR:
            direction = TransactionDirection.OUT
            source_type = TransactionSource.VENDOR_BILL
            description = f"Payment for vendor bill {invoice.invoice_number}"
        else:
            raise ValueError(f"Unknown invoice type: {invoice.invoice_type}")

        # Create Treasury Transaction (atomic, shares the same session)
        await TreasuryService.create_transaction(
            session=session,
            journal_id=journal_id,
            direction=direction,
            source_type=source_type,
            amount=amount_dec,
            created_by_user_id=created_by_user_id,
            reference_id=invoice.invoice_id,
            description=description,
            exchange_rate=rate_dec
        )

        invoice.amount_paid += amount_dec
        if invoice.amount_paid >= invoice.total_amount:
            invoice.status = InvoiceStatus.PAID
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID

        invoice.updated_at = datetime.utcnow()
        await session.flush()
        return invoice

    @staticmethod
    @staticmethod
    async def create_external_expense_invoice(
        session: AsyncSession,
        branch_id: str,
        contact_id: str,
        amount: Decimal | float | str,
        description: str
    ) -> InvoiceModel:
        """
        Utility method for other modules to pre-create a draft purchase invoice (OUT_VENDOR).
        """
        amount_dec = Decimal(str(amount))
        invoice_id = str(uuid.uuid4())

        invoice = InvoiceModel(
            invoice_id=invoice_id,
            branch_id=branch_id,
            invoice_type=InvoiceType.OUT_VENDOR,
            contact_id=contact_id,
            status=InvoiceStatus.DRAFT,
            total_amount=amount_dec,
            amount_paid=Decimal("0.0000")
        )
        session.add(invoice)

        line = InvoiceLineModel(
            line_id=str(uuid.uuid4()),
            invoice_id=invoice_id,
            description=description,
            quantity=Decimal("1.0000"),
            unit_price=amount_dec,
            tax_rate=Decimal("0.0000"),
            subtotal=amount_dec
        )
        session.add(line)

        await session.flush()
        return invoice

    @staticmethod
    async def create_invoice(
        session: AsyncSession,
        branch_id: str,
        contact_id: str,
        invoice_type: InvoiceType | str = InvoiceType.IN_CUSTOMER,
        origin_module: str | None = None,
        origin_reference: str | None = None,
        created_by_user_id: str | None = None,
        lines: list[dict] | None = None
    ) -> InvoiceModel:
        """
        Creates a new draft invoice (customer or vendor) with origin tracking and optional initial lines.
        """
        if isinstance(invoice_type, str):
            try:
                invoice_type = InvoiceType(invoice_type)
            except ValueError:
                invoice_type = InvoiceType.IN_CUSTOMER

        invoice_id = str(uuid.uuid4())
        invoice = InvoiceModel(
            invoice_id=invoice_id,
            branch_id=branch_id,
            contact_id=contact_id,
            invoice_type=invoice_type,
            status=InvoiceStatus.DRAFT,
            total_amount=Decimal("0.0000"),
            amount_paid=Decimal("0.0000"),
            created_by_user_id=created_by_user_id,
            origin_module=origin_module,
            origin_reference=origin_reference
        )
        session.add(invoice)

        if lines:
            for l_data in lines:
                qty = Decimal(str(l_data.get("quantity", 1)))
                price = Decimal(str(l_data.get("unit_price", 0)))
                tax = Decimal(str(l_data.get("tax_rate", 0)))
                subtotal = (qty * price) * (Decimal("1") + tax)
                line = InvoiceLineModel(
                    line_id=str(uuid.uuid4()),
                    invoice_id=invoice_id,
                    description=l_data.get("description", "Ligne de facture"),
                    quantity=qty,
                    unit_price=price,
                    tax_rate=tax,
                    subtotal=subtotal,
                    origin_module=l_data.get("origin_module") or origin_module,
                    origin_reference=l_data.get("origin_reference") or origin_reference
                )
                session.add(line)

        await session.flush()
        return await InvoicingService.calculate_invoice_totals(session, invoice_id)

    @staticmethod
    async def add_invoice_line(
        session: AsyncSession,
        invoice_id: str,
        description: str,
        quantity: Decimal | float | str,
        unit_price: Decimal | float | str,
        tax_rate: Decimal | float | str = Decimal("0.0000"),
        origin_module: str | None = None,
        origin_reference: str | None = None
    ) -> InvoiceLineModel:
        """
        Adds a new line to an existing draft invoice.
        """
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.invoice_id == invoice_id)
            .with_for_update()
        )
        res = await session.execute(stmt)
        invoice = res.scalar_one_or_none()

        if not invoice:
            raise ValueError(f"Facture introuvable avec l'ID {invoice_id}.")

        if invoice.status != InvoiceStatus.DRAFT:
            raise ValueError("Impossible d'ajouter des lignes à une facture validée.")

        qty_dec = Decimal(str(quantity))
        price_dec = Decimal(str(unit_price))
        tax_dec = Decimal(str(tax_rate))
        subtotal = (qty_dec * price_dec) * (Decimal("1") + tax_dec)

        line = InvoiceLineModel(
            line_id=str(uuid.uuid4()),
            invoice_id=invoice_id,
            description=description,
            quantity=qty_dec,
            unit_price=price_dec,
            tax_rate=tax_dec,
            subtotal=subtotal,
            origin_module=origin_module,
            origin_reference=origin_reference
        )
        session.add(line)
        await session.flush()

        await InvoicingService.calculate_invoice_totals(session, invoice_id)
        return line

    @staticmethod
    async def update_invoice_line(
        session: AsyncSession,
        line_id: str,
        requesting_module: str | None = None,
        description: str | None = None,
        quantity: Decimal | float | str | None = None,
        unit_price: Decimal | float | str | None = None,
        tax_rate: Decimal | float | str | None = None
    ) -> InvoiceLineModel:
        """
        Updates a line on a draft invoice with origin module ownership check.
        """
        stmt = (
            select(InvoiceLineModel)
            .where(InvoiceLineModel.line_id == line_id)
            .options(selectinload(InvoiceLineModel.invoice))
            .with_for_update()
        )
        res = await session.execute(stmt)
        line = res.scalar_one_or_none()

        if not line:
            raise ValueError(f"Ligne de facture introuvable (ID: {line_id}).")

        if line.invoice.status != InvoiceStatus.DRAFT:
            raise ValueError("Impossible de modifier une ligne d'une facture validée.")

        # Ownership protection: third-party originated lines can only be updated by origin_module while in DRAFT
        if line.origin_module and line.origin_module != requesting_module:
            raise PermissionError(
                f"La ligne '{line.description}' a été ajoutée par le module '{line.origin_module}' "
                f"et ne peut être modifiée que par celui-ci tant que la facture est en brouillon."
            )

        if description is not None:
            line.description = description
        if quantity is not None:
            line.quantity = Decimal(str(quantity))
        if unit_price is not None:
            line.unit_price = Decimal(str(unit_price))
        if tax_rate is not None:
            line.tax_rate = Decimal(str(tax_rate))

        line.subtotal = (line.quantity * line.unit_price) * (Decimal("1") + line.tax_rate)
        await session.flush()

        await InvoicingService.calculate_invoice_totals(session, line.invoice_id)
        return line

    @staticmethod
    async def delete_invoice_line(
        session: AsyncSession,
        line_id: str,
        requesting_module: str | None = None
    ) -> bool:
        """
        Deletes a line from a draft invoice with origin module ownership check.
        """
        stmt = (
            select(InvoiceLineModel)
            .where(InvoiceLineModel.line_id == line_id)
            .options(selectinload(InvoiceLineModel.invoice))
            .with_for_update()
        )
        res = await session.execute(stmt)
        line = res.scalar_one_or_none()

        if not line:
            raise ValueError(f"Ligne de facture introuvable (ID: {line_id}).")

        if line.invoice.status != InvoiceStatus.DRAFT:
            raise ValueError("Impossible de supprimer une ligne d'une facture validée.")

        # Ownership protection: third-party originated lines can only be deleted by origin_module while in DRAFT
        if line.origin_module and line.origin_module != requesting_module:
            raise PermissionError(
                f"La ligne '{line.description}' a été ajoutée par le module '{line.origin_module}' "
                f"et ne peut être supprimée que par celui-ci tant que la facture est en brouillon."
            )

        invoice_id = line.invoice_id
        await session.delete(line)
        await session.flush()

        await InvoicingService.calculate_invoice_totals(session, invoice_id)
        return True
