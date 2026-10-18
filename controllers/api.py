from core.routing import Request, Response
from modules.melodi_invoicing.services.services import InvoicingService
from modules.melodi_invoicing.models.models import InvoiceModel
from sqlalchemy import select


class InvoicingAPIController:

    @staticmethod
    async def get_invoice_pdf(request: Request, response: Response, invoice_id: str):
        """
        Route to download invoice PDF (stubbed/updated for new fields).
        """
        try:
            # Simple metadata JSON return for PDF placeholder
            async with request.module.app.db.get_session() as session:
                stmt = select(InvoiceModel).where(InvoiceModel.invoice_id == invoice_id)
                res = await session.execute(stmt)
                invoice = res.scalar_one_or_none()

            if not invoice:
                return response.render_json({"error": "Invoice not found"}, status_code=404)

            return response.render_json({
                "invoice_id": invoice.invoice_id,
                "invoice_number": invoice.invoice_number,
                "status": invoice.status.value,
                "total_amount": str(invoice.total_amount),
                "amount_paid": str(invoice.amount_paid)
            }, status_code=200)

        except ValueError as e:
            return response.render_json({"error": str(e)}, status_code=404)
        except Exception as e:
            return response.render_json({"error": f"Internal Error: {str(e)}"}, status_code=500)

    @staticmethod
    async def verify_invoice(request: Request, response: Response, invoice_id: str):
        """
        Public route to verify invoice authenticity.
        """
        try:
            async with request.module.app.db.get_session() as session:
                stmt = select(InvoiceModel).where(InvoiceModel.invoice_id == invoice_id)
                res = await session.execute(stmt)
                invoice = res.scalar_one_or_none()
                
                if not invoice:
                    return response.render_json({"error": "Facture introuvable"}, status_code=404)
                    
                return response.render_json({
                    "valid": True,
                    "invoice": {
                        "invoice_number": invoice.invoice_number,
                        "status": invoice.status.value,
                        "total_amount": str(invoice.total_amount),
                        "date": invoice.created_at.isoformat() if invoice.created_at else None
                    }
                }, status_code=200)
                    
        except Exception as e:
            return response.render_json({"error": f"Erreur de vérification: {str(e)}"}, status_code=500)
