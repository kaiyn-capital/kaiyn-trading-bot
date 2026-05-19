def _to_float(value) -> float:
    return float(value or 0)


def _extract_usdt_balance(assets) -> tuple[float, float, float] | None:
    if isinstance(assets, list):
        for asset in assets:
            coin = asset.get("coin") or asset.get("marginCoin") or asset.get("currency", "")
            if coin != "USDT":
                continue

            available = _to_float(asset.get("available") or asset.get("availableBalance") or asset.get("equity", 0))
            frozen = _to_float(asset.get("frozen") or asset.get("locked") or asset.get("freezeBalance", 0))
            total = available + frozen
            if total > 0:
                return available, frozen, total

    if isinstance(assets, dict) and "USDT" in assets:
        usdt_data = assets["USDT"]
        available = _to_float(
            usdt_data.get("available") or usdt_data.get("availableBalance") or usdt_data.get("equity", 0)
        )
        frozen = _to_float(usdt_data.get("frozen") or usdt_data.get("locked") or usdt_data.get("freezeBalance", 0))
        total = available + frozen
        if total > 0:
            return available, frozen, total

    return None


def format_usdt_balance_text(assets, raw_limit: int, compact: bool) -> str:
    """Format account balance API payload for display."""
    balance_text = "💰 **U本位合约账户余额**\n\n"
    usdt_balance = _extract_usdt_balance(assets)

    if usdt_balance:
        available, frozen, total = usdt_balance
        balance_text += "**USDT:**\n"
        balance_text += f"  可用: {available:.4f}\n"
        balance_text += f"  冻结: {frozen:.4f}\n"
        balance_text += f"  总计: {total:.4f}\n\n"
    else:
        balance_text += "暂无 USDT 资产或余额为零\n\n"
        balance_text += f"📊 **原始API数据：**\n```\n{str(assets)[:raw_limit]}...\n```\n\n"

    balance_text += "ℹ️ **说明：** 仅显示 U 本位合约账户的 USDT 余额"
    return balance_text
