import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, DateTime, ForeignKey, text, Enum, Text
from sqlalchemy.orm import relationship
from core.orm.model import BaseModel, Mapped, mapped_column
from base.config import BaseTables
from modules.melodi_invoicing.config import MelodiInvoicingTables


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class InvoiceType(str, enum.Enum):
    IN_CUSTOMER = "IN_CUSTOMER"
    OUT_VENDOR = "OUT_VENDOR"


class InvoiceModel(BaseModel):
    __tablename__ = MelodiInvoicingTables.INVOICES

    invoice_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    branch_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    invoice_type: Mapped[InvoiceType] = mapped_column(Enum(InvoiceType), index=True, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=True)
    contact_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(f"{BaseTables.CONTACTS}.contact_id", ondelete="RESTRICT"),
        index=True,
        nullable=False
    )
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 4), default=Decimal("0.0000"), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(15, 4), default=Decimal("0.0000"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(100), nullable=True)
    origin_module: Mapped[str] = mapped_column(String(100), index=True, nullable=True, default=None)
    origin_reference: Mapped[str] = mapped_column(String(100), index=True, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.utcnow, default=datetime.utcnow)

    lines: Mapped[list["InvoiceLineModel"]] = relationship(
        "InvoiceLineModel",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class InvoiceLineModel(BaseModel):
    __tablename__ = MelodiInvoicingTables.INVOICE_LINES

    line_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(f"{MelodiInvoicingTables.INVOICES}.invoice_id", ondelete="CASCADE"),
        nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0000"), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    origin_module: Mapped[str] = mapped_column(String(100), index=True, nullable=True, default=None)
    origin_reference: Mapped[str] = mapped_column(String(100), index=True, nullable=True, default=None)

    invoice: Mapped[InvoiceModel] = relationship(
        "InvoiceModel",
        back_populates="lines"
    )
