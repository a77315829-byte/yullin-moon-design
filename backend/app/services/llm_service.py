from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Literal

try:
    from openai import OpenAI
except ImportError:  # OpenAI 키를 쓰지 않는 로컬 규칙 모드 지원
    OpenAI = None  # type: ignore[assignment]
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import AttachmentStatus, EvidenceSource, MailStatus
from ..models import Mail, MailItem, ProductAlias
from .attachment_service import IMAGE_EXTENSIONS, compact_attachment_context
from .customer_matcher import find_or_create_customer
from .price_service import load_alias_map, resolve_standard_product
from .utils import (
    DEFAULT_ALIASES,
    extract_phone,
    extract_quantity,
    normalize_product_name,
    parse_dimensions,
)


class LLMOrderItem(BaseModel):
    product_name: str
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
    evidence: dict[str, str] = Field(default_factory=dict)


class LLMMailAnalysis(BaseModel):
    request_types: list[
        Literal[
            "quotation",
            "production",
            "design_draft",
            "revision",
            "reorder",
            "delivery",
            "payment",
            "inquiry",
            "advertisement",
            "other",
        ]
    ] = Field(default_factory=list)
    commitment_status: Literal["confirmed", "unconfirmed", "unclear"] = "unclear"
    is_business_related: bool = True
    confidence: float = Field(ge=0, le=1)
    customer_organization: str | None = None
    customer_department: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    delivery_place: str | None = None
    payment_terms: str | None = None
    requested_date: str | None = None
    items: list[LLMOrderItem] = Field(default_factory=list)
    summary: str
    reason: str
    missing_information: list[str] = Field(default_factory=list)


class StructuredEvidence(BaseModel):
    """OpenAI Structured Outputs 전용 근거 항목.

    dict[str, str]은 일부 SDK 버전에서 잘못된 strict JSON Schema로
    변환될 수 있으므로 고정 구조의 리스트 항목으로 전달한다.
    """

    model_config = ConfigDict(extra="forbid")

    field_name: str
    source: Literal["CURRENT_MAIL", "ATTACHMENT", "UNKNOWN"]


class StructuredLLMOrderItem(BaseModel):
    """모든 필드를 required로 둔 OpenAI Structured Outputs 전용 모델."""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    specification: str | None
    width_mm: float | None
    height_mm: float | None
    size_name: str | None
    quantity: float | None
    unit: str | None
    paper: str | None
    print_sides: str | None
    material: str | None
    unit_price: int | None
    amount: int | None
    detail_text: str | None
    schedule_note: str | None
    design_request: str | None
    evidence: list[StructuredEvidence]


class StructuredLLMMailAnalysis(BaseModel):
    """OpenAI가 요구하는 strict JSON Schema와 호환되는 응답 모델."""

    model_config = ConfigDict(extra="forbid")

    request_types: list[
        Literal[
            "quotation",
            "production",
            "design_draft",
            "revision",
            "reorder",
            "delivery",
            "payment",
            "inquiry",
            "advertisement",
            "other",
        ]
    ]
    commitment_status: Literal["confirmed", "unconfirmed", "unclear"]
    is_business_related: bool
    confidence: float = Field(ge=0, le=1)
    customer_organization: str | None
    customer_department: str | None
    customer_name: str | None
    customer_phone: str | None
    customer_email: str | None
    delivery_place: str | None
    payment_terms: str | None
    requested_date: str | None
    items: list[StructuredLLMOrderItem]
    summary: str
    reason: str
    missing_information: list[str]


def _convert_structured_analysis(
    parsed: StructuredLLMMailAnalysis,
) -> LLMMailAnalysis:
    """OpenAI 전용 strict 모델을 내부 처리 모델로 변환한다."""

    items: list[LLMOrderItem] = []
    for item in parsed.items:
        evidence = {entry.field_name: entry.source for entry in item.evidence}
        items.append(
            LLMOrderItem(
                product_name=item.product_name,
                specification=item.specification,
                width_mm=item.width_mm,
                height_mm=item.height_mm,
                size_name=item.size_name,
                quantity=item.quantity,
                unit=item.unit,
                paper=item.paper,
                print_sides=item.print_sides,
                material=item.material,
                unit_price=item.unit_price,
                amount=item.amount,
                detail_text=item.detail_text,
                schedule_note=item.schedule_note,
                design_request=item.design_request,
                evidence=evidence,
            )
        )

    return LLMMailAnalysis(
        request_types=list(parsed.request_types),
        commitment_status=parsed.commitment_status,
        is_business_related=parsed.is_business_related,
        confidence=parsed.confidence,
        customer_organization=parsed.customer_organization,
        customer_department=parsed.customer_department,
        customer_name=parsed.customer_name,
        customer_phone=parsed.customer_phone,
        customer_email=parsed.customer_email,
        delivery_place=parsed.delivery_place,
        payment_terms=parsed.payment_terms,
        requested_date=parsed.requested_date,
        items=items,
        summary=parsed.summary,
        reason=parsed.reason,
        missing_information=list(parsed.missing_information),
    )


def _image_data_url(path: Path) -> str:
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/png")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"




def _pdf_page_data_urls(path: Path, max_pages: int = 2) -> list[str]:
    try:
        import fitz
    except ImportError:
        return []
    urls: list[str] = []
    document = fitz.open(path)
    try:
        for page_index in range(min(len(document), max_pages)):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
            urls.append(f"data:image/png;base64,{encoded}")
    finally:
        document.close()
    return urls

def _system_prompt() -> str:
    return """당신은 디자인·인쇄 업체 열린문디자인의 주문 메일 분석 AI다.
메일 본문, 전달된 원본 메일, 첨부파일 추출문을 구분해 분석한다.
메일에 없는 값은 절대 생성하지 않는다. 과거 견적이나 기본 규격이 필요하면 missing_information에 기록한다.
견적 문의와 제작 요청, 시안 요청, 수정 요청은 동시에 존재할 수 있으므로 request_types를 복수로 반환한다.
'지난번처럼', '작년 것처럼'은 현재 메일에 명시된 값이 아니며 고객 이력 검색이 필요한 정보다.
판매자인 열린문디자인을 고객 기관으로 반환하지 않는다.
금액은 메일에 직접 적힌 경우에만 반환하고, 단가표 가격은 별도 검색 엔진이 결정한다.
첨부 이미지나 문서는 제작 문구·규격·수량·디자인 요구의 근거로 사용할 수 있다.
각 품목 evidence는 [{"field_name": "필드명", "source": "CURRENT_MAIL"}] 형식의 목록으로 반환한다. source는 CURRENT_MAIL, ATTACHMENT, UNKNOWN 중 하나다."""


def _user_prompt(mail: Mail, attachment_context: str, max_length: int) -> str:
    return f"""[실제 고객 메일]
보낸 사람: {mail.original_sender_name or ''} <{mail.original_sender_email or ''}>
받는 사람: {mail.original_recipient or ''}
발송 시각: {mail.original_sent_at or ''}
제목: {mail.original_subject or mail.outer_subject or ''}
본문:
{(mail.original_body or '')[:max_length]}

[첨부파일에서 추출한 내용]
{attachment_context or '텍스트로 추출된 내용 없음'}

분석 목표:
1. 고객 기관·담당자·연락처 식별
2. 품목별 규격, 수량, 재질, 용지, 인쇄면, 디자인 문구, 일정 분리
3. 누락된 필수정보 명시
4. 제작 확정 여부와 견적/시안/수정 요청을 구분
"""


def _call_openai(settings: Settings, mail: Mail, attachment_context: str) -> LLMMailAnalysis:
    if OpenAI is None:
        raise RuntimeError("openai 패키지가 설치되지 않았습니다. pip install -r requirements.txt를 실행하세요.")
    client = OpenAI(api_key=settings.openai_api_key)
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": _user_prompt(mail, attachment_context, settings.max_llm_body_length),
        }
    ]
    vision_attachments = []
    if settings.analyze_images:
        for attachment in mail.attachments:
            path = Path(attachment.saved_path)
            if not path.exists():
                continue
            urls: list[str] = []
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                urls = [_image_data_url(path)]
            elif path.suffix.lower() == ".pdf" and attachment.status == AttachmentStatus.IMAGE_PENDING:
                urls = _pdf_page_data_urls(path)
            for url in urls:
                content.append({"type": "input_image", "image_url": url})
                if attachment not in vision_attachments:
                    vision_attachments.append(attachment)
                if len(content) >= 5:
                    break
            if len(content) >= 5:
                break

    # 최신 Responses API를 우선 사용하고, 구버전 SDK에서는 Chat Completions로 폴백한다.
    try:
        response = client.responses.parse(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": _system_prompt()}]},
                {"role": "user", "content": content},
            ],
            text_format=StructuredLLMMailAnalysis,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI structured output is empty")
        for attachment in vision_attachments:
            attachment.status = AttachmentStatus.EXTRACTED
            attachment.analysis_summary = "OpenAI 비전 분석에 반영됨"
        return _convert_structured_analysis(parsed)
    except (AttributeError, TypeError):
        response = client.beta.chat.completions.parse(
            model=settings.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(mail, attachment_context, settings.max_llm_body_length)},
            ],
            response_format=StructuredLLMMailAnalysis,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI structured output is empty")
        return _convert_structured_analysis(parsed)


def _fallback_analysis(session: Session, mail: Mail, attachment_context: str) -> LLMMailAnalysis:
    text = f"{mail.original_subject or ''}\n{mail.original_body or ''}\n{attachment_context}"
    alias_map = load_alias_map(session) or DEFAULT_ALIASES
    detected: list[str] = []
    for standard, aliases in alias_map.items():
        if any(alias.lower() in text.lower() for alias in aliases):
            detected.append(standard)
    detected = list(dict.fromkeys(detected))

    dimension_matches = list(
        re.finditer(
            r"\d+(?:\.\d+)?\s*(?:mm|cm|m|㎜|㎝)?\s*[x×*]\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|㎜|㎝)?",
            text,
            re.I,
        )
    )
    items: list[LLMOrderItem] = []
    if detected:
        # 같은 품목에 여러 규격이 나열되는 메일을 개별 품목으로 분리한다.
        if len(detected) == 1 and dimension_matches:
            product = detected[0]
            dimension_records: list[tuple[str, float | None, float | None, str | None, float | None, str | None]] = []
            seen_dimensions: set[tuple[float | None, float | None, float | None]] = set()
            lines = text.splitlines()
            dimension_pattern = re.compile(
                r"\d+(?:\.\d+)?\s*(?:mm|cm|m|㎜|㎝)?\s*[x×*]\s*"
                r"\d+(?:\.\d+)?\s*(?:mm|cm|m|㎜|㎝)?",
                re.I,
            )
            for line_index, line in enumerate(lines):
                for match in dimension_pattern.finditer(line):
                    dimension_text = match.group(0)
                    width, height, size_name = parse_dimensions(dimension_text)
                    trailing = line[match.end() :]
                    if line_index + 1 < len(lines) and lines[line_index + 1].strip() in {"개", "장", "부", "매", "세트"}:
                        trailing += " " + lines[line_index + 1].strip()
                    multiplier = re.search(
                        r"(?:[x×*]\s*)?(\d+(?:\.\d+)?)\s*(개|장|부|매|세트)",
                        trailing,
                        re.I,
                    )
                    quantity = float(multiplier.group(1)) if multiplier else None
                    unit = multiplier.group(2) if multiplier else None
                    key = (width, height, quantity)
                    if key in seen_dimensions:
                        continue
                    seen_dimensions.add(key)
                    dimension_records.append((dimension_text, width, height, size_name, quantity, unit))

            for dimension_text, width, height, size_name, quantity, unit in dimension_records:
                items.append(
                    LLMOrderItem(
                        product_name=product,
                        specification=dimension_text,
                        width_mm=width,
                        height_mm=height,
                        size_name=size_name,
                        quantity=quantity,
                        unit=unit,
                        evidence={
                            "product_name": EvidenceSource.CURRENT_MAIL,
                            "specification": EvidenceSource.CURRENT_MAIL,
                            "quantity": EvidenceSource.CURRENT_MAIL if quantity is not None else EvidenceSource.UNKNOWN,
                        },
                    )
                )
        else:
            for index, product in enumerate(detected):
                dimension_text = dimension_matches[index].group(0) if index < len(dimension_matches) else None
                width, height, size_name = parse_dimensions(dimension_text or text)
                quantity, unit = extract_quantity(text)
                items.append(
                    LLMOrderItem(
                        product_name=product,
                        specification=dimension_text,
                        width_mm=width,
                        height_mm=height,
                        size_name=size_name,
                        quantity=quantity,
                        unit=unit,
                        detail_text=None,
                        evidence={
                            "product_name": EvidenceSource.CURRENT_MAIL,
                            "specification": EvidenceSource.CURRENT_MAIL if dimension_text else EvidenceSource.UNKNOWN,
                        },
                    )
                )

    request_types: list[str] = []
    if "견적" in text or "금액" in text:
        request_types.append("quotation")
    if any(word in text for word in ("제작", "인쇄", "주문", "발주")):
        request_types.append("production")
    if "시안" in text:
        request_types.append("design_draft")
    if any(word in text for word in ("수정", "변경")):
        request_types.append("revision")
    if not request_types:
        request_types.append("inquiry")

    organization = None
    bracket = re.search(r"\[([^\]]+)\]", mail.original_subject or "")
    if bracket:
        organization = bracket.group(1).strip()

    missing: list[str] = []
    for item in items:
        if item.quantity is None:
            missing.append(f"{item.product_name} 수량")
        if item.product_name in {"현수막", "배너", "포맥스,아크릴"} and (
            item.width_mm is None or item.height_mm is None
        ):
            missing.append(f"{item.product_name} 규격")
    if not items:
        missing.append("품목")

    return LLMMailAnalysis(
        request_types=request_types,
        commitment_status="confirmed" if "제작" in text and "견적" not in text else "unclear",
        is_business_related=True,
        confidence=0.55,
        customer_organization=organization,
        customer_name=mail.original_sender_name,
        customer_email=mail.original_sender_email,
        customer_phone=extract_phone(mail.original_body),
        items=items,
        summary=(mail.original_subject or "주문 메일")[:200],
        reason="OpenAI 키가 없어 제목·본문 키워드와 정규식으로 분석했습니다.",
        missing_information=missing,
    )


def analyze_mail(session: Session, settings: Settings, mail: Mail) -> Mail:
    mail.status = MailStatus.ANALYZING
    mail.error_message = None
    session.commit()

    attachment_context = compact_attachment_context(mail.attachments)
    try:
        if settings.openai_api_key:
            try:
                analysis = _call_openai(settings, mail, attachment_context)
            except Exception as openai_error:
                # API 스키마·네트워크·인증 오류가 발생하더라도 메일 전체를
                # FAILED로 버리지 않고 규칙 기반 분석으로 검토 큐에 남긴다.
                analysis = _fallback_analysis(session, mail, attachment_context)
                analysis.reason = (
                    f"OpenAI 분석 실패({type(openai_error).__name__})로 "
                    f"규칙 기반 분석을 사용했습니다. {analysis.reason}"
                )
                analysis.missing_information = list(
                    dict.fromkeys(
                        [
                            *analysis.missing_information,
                            "AI 분석 결과 수동 검토",
                        ]
                    )
                )
                mail.error_message = (
                    f"OpenAI warning: {type(openai_error).__name__}: "
                    f"{openai_error}"
                )[:2000]
        else:
            analysis = _fallback_analysis(session, mail, attachment_context)
        mail.customer_organization = analysis.customer_organization
        mail.customer_department = analysis.customer_department
        mail.customer_name = analysis.customer_name
        mail.customer_phone = analysis.customer_phone
        mail.customer_email = analysis.customer_email or mail.original_sender_email
        mail.delivery_place = analysis.delivery_place
        mail.payment_terms = analysis.payment_terms
        mail.requested_date = analysis.requested_date
        mail.request_types = list(analysis.request_types)
        mail.commitment_status = analysis.commitment_status
        mail.confidence = analysis.confidence
        mail.summary = analysis.summary
        mail.reason = analysis.reason
        mail.missing_information = analysis.missing_information
        mail.analysis_payload = analysis.model_dump(mode="json")

        customer = find_or_create_customer(
            session,
            analysis.customer_organization,
            email=mail.customer_email,
            phone=mail.customer_phone,
            contact_name=mail.customer_name,
        )
        mail.customer_id = customer.id if customer else None

        session.execute(delete(MailItem).where(MailItem.mail_id == mail.id))
        for index, item in enumerate(analysis.items, start=1):
            normalized = resolve_standard_product(session, item.product_name)
            width = item.width_mm
            height = item.height_mm
            size_name = item.size_name
            if width is None or height is None:
                parsed_width, parsed_height, parsed_size = parse_dimensions(item.specification)
                width = width or parsed_width
                height = height or parsed_height
                size_name = size_name or parsed_size
            session.add(
                MailItem(
                    mail_id=mail.id,
                    position=index,
                    product_name=item.product_name,
                    normalized_product=normalized,
                    specification=item.specification,
                    width_mm=width,
                    height_mm=height,
                    size_name=size_name,
                    quantity=item.quantity,
                    unit=item.unit,
                    paper=item.paper,
                    print_sides=item.print_sides,
                    material=item.material,
                    unit_price=item.unit_price,
                    amount=item.amount,
                    detail_text=item.detail_text,
                    schedule_note=item.schedule_note,
                    design_request=item.design_request,
                    evidence=item.evidence,
                )
            )
        session.commit()
        session.refresh(mail)
        return mail
    except Exception as error:
        session.rollback()
        mail = session.get(Mail, mail.id)
        mail.status = MailStatus.FAILED
        mail.error_message = f"{type(error).__name__}: {error}"
        session.commit()
        raise
