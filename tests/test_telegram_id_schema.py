from sqlalchemy import BigInteger

from app.models import ChannelGroup, PendingOrder, SystemLog, User


def test_telegram_user_identifier_columns_use_big_integer():
    assert isinstance(User.__table__.c.telegram_id.type, BigInteger)
    assert isinstance(PendingOrder.__table__.c.telegram_id.type, BigInteger)
    assert isinstance(SystemLog.__table__.c.telegram_id.type, BigInteger)
    assert isinstance(ChannelGroup.__table__.c.added_by_user_id.type, BigInteger)
