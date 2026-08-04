from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "OPENMOON AI 견적 업무 보조"
    database_url: str = "sqlite:///backend/data/openmoon.db"

    daum_login_id: str = ""
    daum_app_password: str = ""
    imap_server: str = "imap.daum.net"
    imap_port: int = 993
    smtp_server: str = "smtp.daum.net"
    smtp_port: int = 465

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    max_llm_body_length: int = 20_000
    analyze_images: bool = True
    low_confidence_threshold: float = 0.72

    allow_live_send: bool = False

    seller_names: str = "열린문디자인|(주)열린문디자인|주식회사 열린문디자인"
    default_delivery_place: str = "지정장소"
    default_payment_terms: str = "현금 또는 카드결제"
    default_validity: str = "견적일로부터"

    price_table_path: Path = Field(
        default=Path("backend/data/source/price_table.xlsx")
    )
    quotation_template_path: Path = Field(
        default=Path("backend/data/templates/quotation_template.xlsx")
    )
    quotation_template_sheet: str = "0312"
    quotation_history_dir: str = ""

    @field_validator("price_table_path", "quotation_template_path", mode="before")
    @classmethod
    def resolve_project_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "backend" / "data"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def raw_mails_dir(self) -> Path:
        return self.data_dir / "raw_mails"

    @property
    def generated_quotes_dir(self) -> Path:
        return self.data_dir / "generated_quotes"

    @property
    def seller_name_set(self) -> set[str]:
        return {part.strip() for part in self.seller_names.split("|") if part.strip()}

    @property
    def resolved_database_url(self) -> str:
        if not self.database_url.startswith("sqlite:///"):
            return self.database_url
        raw = self.database_url.removeprefix("sqlite:///")
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return f"sqlite:///{path.as_posix()}"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.attachments_dir,
            self.raw_mails_dir,
            self.generated_quotes_dir,
            self.quotation_template_path.parent,
            self.price_table_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache

def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    return settings
