import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # 多管理員支援
    @classmethod
    def get_admin_ids(cls):
        """獲取所有管理員ID列表"""
        admin_ids_str = os.getenv("TELEGRAM_ADMIN_IDS")
        if admin_ids_str:
            return [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
        return []
    
    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """檢查用戶是否為管理員"""
        return user_id in cls.get_admin_ids()
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    # Encryption
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
    
    # Bitget API
    BITGET_API_URL = os.getenv("BITGET_API_URL", "https://api.bitget.com")
    
    # Application
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
    MAINTENANCE_INTERVAL_SECONDS = int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "86400"))
    BACKUP_INTERVAL_SECONDS = int(os.getenv("BACKUP_INTERVAL_SECONDS", "86400"))
    
    # Trading Limits
    MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "10"))
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "1000"))
    
    @classmethod
    def validate(cls):
        """驗證必要的配置項"""
        # 檢查必要的環境變數
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            raise ValueError("Missing TELEGRAM_BOT_TOKEN")
        
        if not os.getenv("ENCRYPTION_KEY"):
            raise ValueError("Missing ENCRYPTION_KEY")
            
        if not os.getenv("TELEGRAM_ADMIN_IDS"):
            raise ValueError("Missing TELEGRAM_ADMIN_IDS")

        cls.validate_database_url()
        
        # 驗證管理員ID格式
        admin_ids = cls.get_admin_ids()
        if not admin_ids:
            raise ValueError("TELEGRAM_ADMIN_IDS contains no valid IDs")
        
        return True

    @classmethod
    def validate_database_url(cls):
        """驗證資料庫連線設定"""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("Missing DATABASE_URL")

        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")

        cls.DATABASE_URL = database_url
        return True
