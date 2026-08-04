from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import Mail, MailItem
from backend.app.services.price_service import find_price_candidates, import_price_table


def test_banner_exact_price(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    price_path = Path(__file__).resolve().parents[1] / "data" / "source" / "price_table.xlsx"
    with Session(engine) as session:
        result = import_price_table(session, price_path)
        assert result["price_rules"] > 5000
        mail = Mail(account="test", uid="1", message_id="<test-price>")
        session.add(mail)
        session.flush()
        item = MailItem(
            mail_id=mail.id,
            product_name="현수막",
            normalized_product="현수막",
            width_mm=4000,
            height_mm=600,
            quantity=1,
        )
        session.add(item)
        session.commit()
        candidates = find_price_candidates(session, item)
        assert candidates[0].exact is True
        assert candidates[0].amount == 44_000
        assert candidates[0].source_cell == "J5"
