from pathlib import Path

from app import order_flow
from app.bot_admin_handlers import AdminHandlersMixin
from app.order_types import ContractRules, OrderPreview
from app.order_validation import parse_contract_rules, validate_order_preview


def test_order_flow_keeps_compatibility_exports():
    assert order_flow.OrderPreview is OrderPreview
    assert order_flow.ContractRules is ContractRules
    assert order_flow.parse_contract_rules is parse_contract_rules
    assert order_flow.validate_order_preview is validate_order_preview
    assert "OrderPreview" in order_flow.__all__
    assert "validate_order_preview" in order_flow.__all__


def test_admin_handlers_include_channel_topic_commands():
    assert hasattr(AdminHandlersMixin, "set_channel_topic_command")
    assert hasattr(AdminHandlersMixin, "clear_channel_topic_command")


def test_main_entrypoint_has_no_replacement_character():
    main_source = Path("app/main.py").read_text(encoding="utf-8")
    assert "�" not in main_source
    assert "🚀 啟動 Bitget Telegram 交易機器人..." in main_source
