# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram bot for Bitget cryptocurrency trading. The bot allows users to connect their Bitget API credentials and execute trades through Telegram commands. It includes user management, encrypted API key storage, trade execution, and administrative features for managing traders and channels.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Database Operations
```bash
# Initialize database and create tables
python app/main.py --create-tables

# Check database connection
python app/main.py --check-db

# Generate encryption key for .env
python app/main.py --generate-key
```

### Running the Bot
```bash
# Start the bot
python app/main.py

# Initialize project structure (creates directories and .env template)
python app/main.py --init
```

### Testing
```bash
# Run basic functionality tests
python test_fixes.py

# Run detailed testing
python test_fixes_detailed.py

# Test signal flow functionality  
python test_signal_flow.py

# Test bot improvements
python test_bot_improvements.py
```

## Architecture Overview

### Core Components

**Database Layer (`app/database.py`)**
- Uses SQLAlchemy with both sync and async session support
- `DatabaseManager` class handles connection management with context managers
- Supports both SQLite (development) and PostgreSQL (production)
- Repository pattern for data access (`get_user_repo`, `get_trade_repo`, etc.)

**Models (`app/models.py`)**
- `User`: Stores encrypted API credentials, trading preferences, and trader permissions
- `Trade`: Records all trading activity with Bitget order tracking
- `NotificationLog`: Message logging system
- `TradingPair`: Trading pair metadata and constraints
- `ChannelGroup`: Manages Telegram channels/groups for signal forwarding
- `SystemLog`: Application-wide logging

**Bot Logic (`app/bot.py`)**
- `TelegramBot` class handles all Telegram interactions
- Conversation handlers for multi-step workflows (API setup, trading)
- Command handlers for bot functionality (`/start`, `/setapi`, `/trade`, etc.)
- Callback query handlers for inline keyboards
- Admin functionality for managing traders and channels

**Bitget Integration (`app/bitget_api.py`)**
- `BitgetAPIClient`: Low-level API client with authentication
- `BitgetTradeManager`: High-level trading operations
- Request signing, error handling, and rate limiting
- Order validation and execution

**Security (`app/encryption.py`)**
- `EncryptionManager`: Fernet-based encryption for API keys
- `KeyGenerator`: Utility for generating encryption keys
- All sensitive data is encrypted before database storage

### Key Patterns

**Configuration Management**
- Environment variables loaded via `python-dotenv`
- `Config` class centralizes all configuration with validation
- Separate development/production database URLs

**Error Handling**
- Global error handler in bot catches and logs all exceptions
- Custom exception types for API errors (`BitgetAPIError`)
- User-friendly error messages with system error logging

**State Management**
- Conversation states for multi-step user interactions
- User session data stored in context
- Persistent state in database models

**Permissions System**
- Admin-only commands checked via `Config.TELEGRAM_ADMIN_ID`
- Trader permissions via `is_trader` field on User model
- Combined permission checks in `_is_trader_or_admin` method

## Database Schema Notes

The database uses a repository pattern for clean separation. Key relationships:
- Users have many Trades and NotificationLogs
- All API credentials are encrypted before storage
- The `is_trader` field grants signal-sending permissions
- SystemLog captures application events for monitoring

## Common Issues

**Database Migration**
- When adding new model fields, manually update existing SQLite databases with `ALTER TABLE` statements
- The `is_trader` field was added as a migration and may need manual addition to existing databases

**API Key Security**  
- All Bitget API credentials are encrypted using Fernet before database storage
- Encryption key must be 32 bytes base64 encoded in ENCRYPTION_KEY environment variable
- Test encryption setup using `python app/main.py --generate-key`

**Conversation State**
- Multi-step commands use conversation handlers with numbered states
- State constants defined at module level (WAITING_API_KEY, WAITING_SECRET_KEY, etc.)
- Context.user_data used for temporary state storage

## Configuration Requirements

Essential environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `TELEGRAM_ADMIN_ID`: Admin user's Telegram ID (numeric)  
- `ENCRYPTION_KEY`: 32-byte base64 key for API credential encryption
- `DATABASE_URL`: SQLite for development, PostgreSQL for production
- `BITGET_API_URL`: Usually "https://api.bitget.com"

## Testing Strategy

The project includes several test files that verify core functionality:
- Database connectivity and schema validation
- Bot command handling and conversation flows  
- API integration and encryption/decryption
- Signal forwarding and trading workflows

Test files follow the pattern `test_*.py` and can be run directly with Python.