import asyncio
import time
from app.bot_admin_messaging import AdminMessaging
from types import SimpleNamespace
from telegram.error import TelegramError

class FakeBot:
    def __init__(self):
        self.channel_repo = SimpleNamespace(
            get_active_channels=self.get_active_channels
        )
        self._sender_username = "admin"

    async def get_active_channels(self):
        return [SimpleNamespace(chat_id=str(i), message_thread_id=None) for i in range(100)]

    async def _require_admin(self, update):
        return SimpleNamespace(id=1)

    def _get_sender_username(self, update):
        return "admin"

class FakeMessage:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kwargs):
        return SimpleNamespace(edit_text=self.edit_text)
    async def edit_text(self, text, **kwargs):
        pass

class FakeContextBot:
    async def send_message(self, **kwargs):
        await asyncio.sleep(0.01) # Simulate network IO
        if int(kwargs['chat_id']) % 10 == 0:
            raise TelegramError("Mock error")

class FakeContext:
    def __init__(self):
        self.args = ["test", "message"]
        self.bot = FakeContextBot()

# Mock emit_audit_event
import app.bot_admin_messaging
async def mock_emit(*args, **kwargs):
    pass
app.bot_admin_messaging.emit_audit_event = mock_emit

async def main():
    bot = FakeBot()
    messaging = AdminMessaging(bot)

    update = SimpleNamespace(message=FakeMessage())
    context = FakeContext()

    start_time = time.time()
    await messaging.admin_broadcast_command(update, context)
    duration = time.time() - start_time

    print(f"Broadcast to 100 channels took: {duration:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
