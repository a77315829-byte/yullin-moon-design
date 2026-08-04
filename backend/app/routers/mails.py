from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..database import get_db
from ..models import Attachment, Mail, MailItem, ReviewIssue
from ..schemas import (
    AnalysisUpdate,
    HistoryCandidateOut,
    MailDetailOut,
    MailListOut,
    MailSyncRequest,
    PriceCandidateOut,
)
from ..services.history_service import get_history_candidates
from ..services.llm_service import analyze_mail
from ..services.mail_service import import_eml_bytes, sync_imap
from ..services.price_service import find_price_candidates, resolve_standard_product
from ..services.review_service import evaluate_mail_readiness

router = APIRouter(prefix="/api/mails", tags=["mails"])


def _mail_query():
    return select(Mail).options(
        selectinload(Mail.attachments),
        selectinload(Mail.items),
        selectinload(Mail.reviews),
        selectinload(Mail.drafts),
    )


@router.get("", response_model=list[MailListOut])
def list_mails(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
):
    query = select(Mail).order_by(Mail.original_sent_at.desc().nullslast(), Mail.id.desc())
    if status:
        query = query.where(Mail.status == status)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            Mail.original_subject.ilike(pattern)
            | Mail.original_sender_name.ilike(pattern)
            | Mail.customer_organization.ilike(pattern)
        )
    return session.scalars(query.limit(limit)).all()


@router.get("/attachments/{attachment_id}/file")
def get_attachment(attachment_id: int, session: Session = Depends(get_db)):
    attachment = session.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "첨부파일을 찾을 수 없습니다.")
    path = Path(attachment.saved_path)
    if not path.exists():
        raise HTTPException(404, "저장된 첨부파일이 없습니다.")
    return FileResponse(path, filename=attachment.filename, media_type=attachment.content_type)


@router.get("/{mail_id}", response_model=MailDetailOut)
def get_mail(mail_id: int, session: Session = Depends(get_db)):
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    return mail


@router.post("/sync")
def sync_mailbox(
    request: MailSyncRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        return sync_imap(
            session,
            settings,
            limit=request.limit,
            include_existing=request.include_existing,
        )
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.post("/import-eml", response_model=list[MailListOut])
def upload_eml(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result: list[Mail] = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".eml"):
            raise HTTPException(400, f"EML 파일만 업로드할 수 있습니다: {file.filename}")
        result.append(import_eml_bytes(session, settings, file.file.read()))
    return result


@router.post("/{mail_id}/analyze", response_model=MailDetailOut)
def run_analysis(
    mail_id: int,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    try:
        analyze_mail(session, settings, mail)
        mail = session.scalar(_mail_query().where(Mail.id == mail_id))
        evaluate_mail_readiness(session, settings, mail)
        return session.scalar(_mail_query().where(Mail.id == mail_id))
    except Exception as error:
        raise HTTPException(500, f"메일 분석 실패: {error}") from error


@router.patch("/{mail_id}/analysis", response_model=MailDetailOut)
def update_analysis(
    mail_id: int,
    request: AnalysisUpdate,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    for field in (
        "customer_organization",
        "customer_department",
        "customer_name",
        "customer_phone",
        "customer_email",
        "delivery_place",
        "payment_terms",
        "requested_date",
        "request_types",
        "commitment_status",
        "summary",
        "reason",
    ):
        setattr(mail, field, getattr(request, field))

    session.execute(delete(MailItem).where(MailItem.mail_id == mail.id))
    session.flush()
    for position, item in enumerate(request.items, start=1):
        data = item.model_dump(exclude={"id"})
        data["normalized_product"] = data.get("normalized_product") or resolve_standard_product(
            session, data["product_name"]
        )
        session.add(MailItem(mail_id=mail.id, position=position, **data))
    session.commit()
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    evaluate_mail_readiness(session, settings, mail)
    return session.scalar(_mail_query().where(Mail.id == mail_id))


@router.get("/{mail_id}/price-candidates", response_model=list[PriceCandidateOut])
def price_candidates(mail_id: int, session: Session = Depends(get_db)):
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    result = []
    for item in mail.items:
        result.extend(find_price_candidates(session, item))
    return [PriceCandidateOut(**asdict(candidate)) for candidate in result]


@router.get("/{mail_id}/history", response_model=list[HistoryCandidateOut])
def history_candidates(mail_id: int, session: Session = Depends(get_db)):
    mail = session.scalar(_mail_query().where(Mail.id == mail_id))
    if not mail:
        raise HTTPException(404, "메일을 찾을 수 없습니다.")
    results: list[HistoryCandidateOut] = []
    for item in mail.items:
        for history_item, quotation in get_history_candidates(session, mail, item):
            results.append(
                HistoryCandidateOut(
                    quotation_id=quotation.id,
                    quotation_date=quotation.quotation_date,
                    customer_name=quotation.customer_name,
                    product_name=history_item.product_name,
                    specification=history_item.specification,
                    width_mm=history_item.width_mm,
                    height_mm=history_item.height_mm,
                    quantity=history_item.quantity,
                    unit_price=history_item.unit_price,
                    amount=history_item.amount,
                    source_file=quotation.source_file,
                    source_sheet=quotation.source_sheet,
                )
            )
    return results
