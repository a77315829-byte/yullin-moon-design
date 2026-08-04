from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..schemas import ImportRequest, ImportResult
from ..services.history_service import import_quotation_history
from ..services.price_service import import_price_table

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/price-table", response_model=ImportResult)
def import_prices(
    request: ImportRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    path = Path(request.path) if request.path else settings.price_table_path
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        counts = import_price_table(session, path)
        return ImportResult(
            processed=1,
            imported=sum(counts.values()),
            message="단가표 가져오기가 완료되었습니다.",
            details=counts,
        )
    except Exception as error:
        raise HTTPException(400, str(error)) from error


@router.post("/quotation-history", response_model=ImportResult)
def import_history(
    request: ImportRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    raw_path = request.path or settings.quotation_history_dir
    if not raw_path:
        raise HTTPException(400, "견적서 전체 폴더 경로를 입력하세요.")
    root = Path(raw_path)
    try:
        stats = import_quotation_history(
            session,
            root,
            settings.data_dir / "import_summary.csv",
            settings.data_dir / "import_errors.csv",
        )
        return ImportResult(
            processed=stats.processed,
            imported=stats.imported,
            review_required=stats.review_required,
            failed=stats.failed,
            message="기존 견적 이력 가져오기가 완료되었습니다.",
            details={
                "summary_csv": str(settings.data_dir / "import_summary.csv"),
                "error_csv": str(settings.data_dir / "import_errors.csv"),
            },
        )
    except Exception as error:
        raise HTTPException(400, str(error)) from error
