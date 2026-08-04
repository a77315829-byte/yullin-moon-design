from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import AttachmentStatus, MailStatus, Severity
from ..models import Mail, MailItem, ReviewIssue
from .history_service import get_history_candidates
from .price_service import find_price_candidates

PRODUCT_REQUIREMENTS: dict[str, list[str]] = {
    "현수막": ["width_mm", "height_mm", "quantity"],
    "육교현수막": ["width_mm", "height_mm", "quantity"],
    "배너": ["width_mm", "height_mm", "quantity"],
    "친환경배너": ["width_mm", "height_mm", "quantity"],
    "명함": ["quantity", "paper", "print_sides"],
    "포스터": ["quantity"],
    "전단지": ["quantity"],
    "리플릿": ["quantity"],
    "카다로그": ["quantity"],
    "포맥스,아크릴": ["width_mm", "height_mm", "quantity", "material"],
    "골지,허니콤보드": ["width_mm", "height_mm", "quantity", "material"],
    "어깨띠": ["quantity"],
    "책제본": ["quantity"],
}

FIELD_LABELS = {
    "width_mm": "가로 규격",
    "height_mm": "세로 규격",
    "quantity": "수량",
    "paper": "용지",
    "print_sides": "단면·양면 여부",
    "material": "재질",
}


def _history_suggestions(session: Session, mail: Mail, item: MailItem, field: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    rows = get_history_candidates(session, mail, item, limit=10)
    seen: set[Any] = set()
    for history_item, quotation in rows:
        value = getattr(history_item, field, None)
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        suggestions.append(
            {
                "value": value,
                "quotation_date": str(quotation.quotation_date or ""),
                "specification": history_item.specification,
                "source_file": quotation.source_file,
                "source_sheet": quotation.source_sheet,
            }
        )
        if len(suggestions) >= 5:
            break
    return suggestions


def _add_issue(
    session: Session,
    mail_id: int,
    code: str,
    message: str,
    field_name: str | None = None,
    severity: str = Severity.BLOCKING,
    suggestions: list[Any] | None = None,
) -> None:
    session.add(
        ReviewIssue(
            mail_id=mail_id,
            code=code,
            field_name=field_name,
            message=message,
            severity=severity,
            suggestions=suggestions or [],
            source="AUTO",
        )
    )


def evaluate_mail_readiness(session: Session, settings: Settings, mail: Mail) -> list[ReviewIssue]:
    # 사용자가 해결한 기록은 남기고, 자동 미해결 이슈만 다시 만든다.
    session.execute(
        delete(ReviewIssue).where(
            ReviewIssue.mail_id == mail.id,
            ReviewIssue.source == "AUTO",
            ReviewIssue.resolved.is_(False),
        )
    )
    session.flush()

    if not mail.customer_id and not mail.customer_organization:
        _add_issue(
            session,
            mail.id,
            "CUSTOMER_NOT_IDENTIFIED",
            "고객 또는 기관을 식별할 수 없습니다.",
            "customer_organization",
        )

    if mail.confidence is not None and mail.confidence < settings.low_confidence_threshold:
        _add_issue(
            session,
            mail.id,
            "LOW_ANALYSIS_CONFIDENCE",
            f"메일 분석 신뢰도가 {mail.confidence:.2f}로 기준보다 낮습니다.",
            severity=Severity.WARNING,
        )

    if not mail.items:
        _add_issue(session, mail.id, "NO_ORDER_ITEM", "주문 품목을 확인할 수 없습니다.", "items")

    for item in mail.items:
        product = item.normalized_product or item.product_name
        requirements = PRODUCT_REQUIREMENTS.get(product, ["quantity"])
        for field in requirements:
            value = getattr(item, field, None)
            if value not in (None, ""):
                continue
            suggestions = _history_suggestions(session, mail, item, field)
            _add_issue(
                session,
                mail.id,
                f"MISSING_{field.upper()}",
                f"{product}의 {FIELD_LABELS.get(field, field)}이(가) 누락되었습니다.",
                f"items.{item.id}.{field}",
                suggestions=suggestions,
            )

        # 담당자가 단가를 직접 확정한 경우 단가표 정확일치 검사를 다시 차단하지 않는다.
        if item.unit_price is not None and item.confirmed:
            candidates = []
        else:
            candidates = find_price_candidates(session, item)
        if item.unit_price is not None and item.confirmed:
            pass
        elif not candidates:
            _add_issue(
                session,
                mail.id,
                "NO_PRICE_CANDIDATE",
                f"{product}에 적용할 가격 후보를 찾지 못했습니다.",
                f"items.{item.id}.unit_price",
            )
        elif not any(candidate.exact for candidate in candidates):
            _add_issue(
                session,
                mail.id,
                "PRICE_NOT_EXACT",
                f"{product}의 현재 조건과 정확히 일치하는 단가가 없습니다. 후보를 검토하세요.",
                f"items.{item.id}.unit_price",
                suggestions=[asdict(candidate) for candidate in candidates],
            )

    for attachment in mail.attachments:
        if attachment.status in {
            AttachmentStatus.MANUAL_REVIEW,
            AttachmentStatus.FAILED,
            AttachmentStatus.IMAGE_PENDING,
        }:
            _add_issue(
                session,
                mail.id,
                "ATTACHMENT_REVIEW_REQUIRED",
                f"첨부파일 '{attachment.filename}'의 자동 분석이 완료되지 않았습니다.",
                f"attachments.{attachment.id}",
            )

    reference_words = ("지난번", "저번", "작년", "이전처럼", "전에 했던", "그때처럼")
    body = f"{mail.original_subject or ''} {mail.original_body or ''}"
    if any(word in body for word in reference_words):
        history_found = any(get_history_candidates(session, mail, item, limit=1) for item in mail.items)
        if not history_found:
            _add_issue(
                session,
                mail.id,
                "UNRESOLVED_HISTORY_REFERENCE",
                "이전 제작물을 가리키는 표현이 있지만 연결할 고객 견적 이력을 찾지 못했습니다.",
                "history_reference",
            )

    if mail.missing_information:
        for missing in mail.missing_information:
            _add_issue(
                session,
                mail.id,
                "LLM_REPORTED_MISSING",
                f"AI가 누락 정보로 판단했습니다: {missing}",
                severity=Severity.WARNING,
            )

    session.flush()
    unresolved = session.scalars(
        select(ReviewIssue).where(ReviewIssue.mail_id == mail.id, ReviewIssue.resolved.is_(False))
    ).all()
    blocking = [issue for issue in unresolved if issue.severity == Severity.BLOCKING]
    mail.status = MailStatus.REVIEW_REQUIRED if blocking else MailStatus.READY_FOR_QUOTE
    session.commit()
    session.refresh(mail)
    return unresolved


def apply_review_resolution(session: Session, issue: ReviewIssue, value: Any) -> None:
    issue.resolution_value = value
    issue.resolved = True

    if issue.field_name and issue.field_name.startswith("items."):
        _, item_id, field = issue.field_name.split(".", 2)
        item = session.get(MailItem, int(item_id))
        if item and hasattr(item, field):
            setattr(item, field, value)
            item.confirmed = True
    elif issue.field_name and issue.field_name.startswith("customer_"):
        mail = session.get(Mail, issue.mail_id)
        if mail and hasattr(mail, issue.field_name):
            setattr(mail, issue.field_name, value)
    session.commit()
