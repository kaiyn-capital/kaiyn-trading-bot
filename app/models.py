import json
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    # API 配置（加密存儲）
    encrypted_api_key = Column(Text, nullable=True)
    encrypted_secret_key = Column(Text, nullable=True)
    encrypted_passphrase = Column(Text, nullable=True)

    # 狀態
    is_active = Column(Boolean, default=True)
    is_api_connected = Column(Boolean, default=False)

    # 設定
    daily_trade_limit = Column(Integer, default=10)
    max_position_size = Column(Float, default=1000.0)
    enable_notifications = Column(Boolean, default=True)

    # 交易設定
    default_stop_loss_percent = Column(Float, default=2.0)  # 預設止損百分比
    default_trade_amount = Column(Float, default=100.0)  # 預設交易金額
    auto_stop_loss = Column(Boolean, default=True)  # 是否自動設置止損
    fixed_risk_amount = Column(Float, nullable=True)  # 固定風險金額(1R)

    # 發單員權限
    is_trader = Column(Boolean, default=False)  # 是否為發單員

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # 關聯
    trades = relationship("Trade", back_populates="user")
    notifications = relationship("NotificationLog", back_populates="user")
    pending_orders = relationship("PendingOrder", back_populates="user")
    signal_records = relationship("SignalRecord", back_populates="user")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    # 交易信息
    symbol = Column(String, nullable=False)  # 例如: BTCUSDT
    side = Column(String, nullable=False)  # buy/sell
    order_type = Column(String, nullable=False)  # market/limit
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # limit 單才有價格

    # Bitget 訂單信息
    bitget_order_id = Column(String, unique=True, nullable=True)
    client_order_id = Column(String, unique=True)

    # 執行結果
    status = Column(String, default="pending")  # pending/filled/cancelled/failed
    filled_quantity = Column(Float, default=0.0)
    avg_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    fee = Column(Float, default=0.0)

    # 錯誤信息
    error_message = Column(Text, nullable=True)

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)

    # 關聯
    user = relationship("User", back_populates="trades")
    pending_orders = relationship("PendingOrder", back_populates="trade")


class PendingOrder(Base):
    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)

    # Signal and computed order data
    symbol = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # long/short
    order_mode = Column(String, default="market", nullable=False)  # market/limit
    limit_price = Column(Float, nullable=True)
    entry_lower = Column(Float, nullable=True)
    entry_upper = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    position_value = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)

    # Lifecycle
    status = Column(String, default="pending", nullable=False, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)
    error_message = Column(Text, nullable=True)

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)

    # 關聯
    user = relationship("User", back_populates="pending_orders")
    trade = relationship("Trade", back_populates="pending_orders")


class SignalRecord(Base):
    __tablename__ = "signal_records"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(16), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    sender_telegram_id = Column(BigInteger, nullable=False, index=True)
    sender_username = Column(String, nullable=True)

    symbol = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    entry_lower = Column(Float, nullable=False)
    entry_upper = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit_levels = Column(Text, nullable=False)
    remark = Column(Text, nullable=True)
    signal_text = Column(Text, nullable=False)
    granularity = Column(String, nullable=False)

    status = Column(String, default="preview_pending", nullable=False, index=True)
    chart_status = Column(String, nullable=True)
    chart_error = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="signal_records")
    channel_messages = relationship(
        "SignalChannelMessage",
        back_populates="signal_record",
        cascade="all, delete-orphan",
    )

    def set_take_profit_levels(self, levels: list[float]):
        self.take_profit_levels = json.dumps(levels, ensure_ascii=False)

    def get_take_profit_levels(self) -> list[float]:
        if not self.take_profit_levels:
            return []
        return [float(level) for level in json.loads(self.take_profit_levels)]


class SignalChannelMessage(Base):
    __tablename__ = "signal_channel_messages"

    id = Column(Integer, primary_key=True, index=True)
    signal_record_id = Column(Integer, ForeignKey("signal_records.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False, index=True)
    message_thread_id = Column(Integer, nullable=True)
    telegram_message_id = Column(Integer, nullable=False)
    sent_as = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    signal_record = relationship("SignalRecord", back_populates="channel_messages")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    # 通知內容
    message_type = Column(String, nullable=False)  # trade/error/info
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)

    # 發送狀態
    is_sent = Column(Boolean, default=False)
    telegram_message_id = Column(Integer, nullable=True)

    # 額外數據
    extra_data = Column(Text, nullable=True)  # JSON 格式

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    # 關聯
    user = relationship("User", back_populates="notifications")

    def set_extra_data(self, data: dict):
        """設置額外數據"""
        self.extra_data = json.dumps(data, ensure_ascii=False)

    def get_extra_data(self) -> dict:
        """獲取額外數據"""
        if self.extra_data:
            return json.loads(self.extra_data)
        return {}


class TradingPair(Base):
    __tablename__ = "trading_pairs"

    id = Column(Integer, primary_key=True, index=True)

    # 交易對信息
    symbol = Column(String, unique=True, nullable=False)
    base_currency = Column(String, nullable=False)
    quote_currency = Column(String, nullable=False)

    # 交易限制
    min_order_size = Column(Float, nullable=False)
    max_order_size = Column(Float, nullable=False)
    min_price = Column(Float, nullable=False)
    max_price = Column(Float, nullable=False)
    price_precision = Column(Integer, nullable=False)
    quantity_precision = Column(Integer, nullable=False)

    # 狀態
    is_active = Column(Boolean, default=True)
    is_trading_enabled = Column(Boolean, default=True)

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChannelGroup(Base):
    __tablename__ = "channel_groups"

    id = Column(Integer, primary_key=True, index=True)

    # 頻道/群組信息
    chat_id = Column(String, unique=True, nullable=False)  # Telegram Chat ID
    chat_type = Column(String, nullable=False)  # channel/group/supergroup
    title = Column(String, nullable=True)
    username = Column(String, nullable=True)  # @username

    # 功能設置
    is_active = Column(Boolean, default=True)
    auto_forward_signals = Column(Boolean, default=True)  # 自動轉發交易信號
    forward_with_buttons = Column(Boolean, default=True)  # 轉發時包含交易按鈕
    message_thread_id = Column(Integer, nullable=True)  # Telegram forum topic ID
    thread_title = Column(String, nullable=True)  # 管理員填寫的話題備註名稱

    # 管理信息
    added_by_user_id = Column(BigInteger, nullable=False)  # 添加此頻道的管理員 ID
    description = Column(String, nullable=True)  # 頻道描述

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)

    # 日誌信息
    level = Column(String, nullable=False)  # INFO/WARNING/ERROR/CRITICAL
    message = Column(Text, nullable=False)
    module = Column(String, nullable=False)
    function = Column(String, nullable=True)

    # 用戶相關
    user_id = Column(Integer, nullable=True)
    telegram_id = Column(BigInteger, nullable=True)

    # 額外信息
    extra_data = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)

    # 時間戳
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_extra_data(self, data: dict):
        """設置額外數據"""
        self.extra_data = json.dumps(data, ensure_ascii=False)

    def get_extra_data(self) -> dict:
        """獲取額外數據"""
        if self.extra_data:
            return json.loads(self.extra_data)
        return {}
