from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AttachmentOut(ORMModel):
    id: int
    filename: str
    content_type: str | None
    size_bytes: int
    status: str
    extracted_text: str | None = None
    analysis_summary: str | None = None
    error_message: str | None = None


class MailItemBase(BaseModel):
    product_name: str
    normalized_product: str | None = None
    specification: str | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    size_name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    paper: str | None = None
    print_sides: str | None = None
    material: str | None = None
    unit_price: int | None = None
    amount: int | None = None
    detail_text: str | None = None
    schedule_note: str | None = None
    design_request: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class MailItemOut(MailItemBase, ORMModel):
    id: int
    position: int


class MailItemUpdate(MailItemBase):
    id: int | None = None


class ReviewIssueOut(ORMModel):
    id: int
    code: str
    field_name: str | None
    message: str
    severity: str
    suggestions: list[Any] = Field(default_factory=list)
    resolved: bool
    resolution_value: Any | None = None


class MailListOut(ORMModel):
    id: int
    status: str
    outer_subject: str | None
    original_subject: str | None
    original_sender_name: str | None
    original_sender_email: str | None
    customer_organization: str | None
    original_sent_at: datetime | None
    summary: str | None
    created_at: datetime


class MailDetailOut(MailListOut):
    forward_depth: int
    outer_sender_name: str | None
    outer_sender_email: str | None
    outer_recipient: str | None
    outer_sent_at: datetime | None
    outer_body: str | None
    original_recipient: str | None
    original_body: str | None
    customer_department: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    delivery_place: str | None
    payment_terms: str | None
    requested_date: str | None
    request_types: list[str] = Field(default_factory=list)
    commitment_status: str | None
    confidence: float | None
    reason: str | None
    missing_information: list[str] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    items: list[MailItemOut] = Field(default_factory=list)
    reviews: list[ReviewIssueOut] = Field(default_factory=list)


class AnalysisUpdate(BaseModel):
    customer_organization: str | None = None
    customer_department: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    delivery_place: str | None = None
    payment_terms: str | None = None
    requested_date: str | None = None
    request_types: list[str] = Field(default_factory=list)
    commitment_status: str | None = None
    summary: str | None = None
    reason: str | None = None
    items: list[MailItemUpdate] = Field(default_factory=list)


class ReviewResolveRequest(BaseModel):
    resolution_value: Any | None = None
    apply_to_field: bool = True


class PriceCandidateOut(BaseModel):
    item_id: int
    product_name: str
    amount: int | None
    exact: bool
    score: float
    source_sheet: str
    source_cell: str
    context: str | None = None
    vat: str | None = None
    automation_status: str | None = None
    reason: str


class HistoryCandidateOut(BaseModel):
    quotation_id: int
    quotation_date: date | None
    customer_name: str
    product_name: str
    specification: str | None
    width_mm: float | None
    height_mm: float | None
    quantity: float | None
    unit_price: int | None
    amount: int | None
    source_file: str
    source_sheet: str


class DraftItemOut(ORMModel):
    id: int
    position: int
    product_name: str
    specification: str | None
    quantity: float | None
    unit: str | None
    unit_price: int | None
    amount: int | None
    note: str | None
    price_source: dict[str, Any] = Field(default_factory=dict)


class DraftOut(ORMModel):
    id: int
    mail_id: int
    status: str
    file_path: str
    customer_name: str
    total_amount: int | None
    email_subject: str | None
    email_body: str | None
    approved_at: datetime | None
    sent_at: datetime | None
    sent_to: str | None
    error_message: str | None
    items: list[DraftItemOut] = Field(default_factory=list)


class ImportRequest(BaseModel):
    path: str | None = None


class ImportResult(BaseModel):
    processed: int = 0
    imported: int = 0
    review_required: int = 0
    failed: int = 0
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MailSyncRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    include_existing: bool = False


class EmailPreview(BaseModel):
    subject: str
    body: str
    recipient: str | None
    attachment_path: str | None


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    database: str
    openai_configured: bool
    mail_configured: bool
    live_send_enabled: bool
