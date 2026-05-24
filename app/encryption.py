import base64
import binascii
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class EncryptionManager:
    """加密管理器 - 用於加密存儲 API 金鑰"""

    def __init__(self, encryption_key: str):
        """
        初始化加密管理器

        Args:
            encryption_key: Base64 編碼的加密金鑰
        """
        try:
            self.key = encryption_key.encode()
            self.fernet = Fernet(self.key)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise ValueError("Invalid encryption key") from e

    def encrypt(self, plaintext: str) -> str:
        """
        加密字符串

        Args:
            plaintext: 需要加密的明文

        Returns:
            Base64 編碼的加密文本
        """
        if not plaintext:
            return ""

        try:
            encrypted = self.fernet.encrypt(plaintext.encode())
            return base64.b64encode(encrypted).decode()
        except (TypeError, ValueError) as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """
        解密字符串

        Args:
            ciphertext: Base64 編碼的加密文本

        Returns:
            解密後的明文
        """
        if not ciphertext:
            return ""

        try:
            encrypted_data = base64.b64decode(ciphertext.encode())
            decrypted = self.fernet.decrypt(encrypted_data)
            return decrypted.decode()
        except (binascii.Error, InvalidToken, TypeError, UnicodeDecodeError, ValueError) as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_api_credentials(self, api_key: str, secret_key: str, passphrase: str) -> tuple:
        """
        加密 API 憑證

        Args:
            api_key: API 金鑰
            secret_key: 密鑰
            passphrase: 通行短語

        Returns:
            (encrypted_api_key, encrypted_secret_key, encrypted_passphrase)
        """
        return (
            self.encrypt(api_key),
            self.encrypt(secret_key),
            self.encrypt(passphrase),
        )

    def decrypt_api_credentials(
        self,
        encrypted_api_key: str,
        encrypted_secret_key: str,
        encrypted_passphrase: str,
    ) -> tuple:
        """
        解密 API 憑證

        Args:
            encrypted_api_key: 加密的 API 金鑰
            encrypted_secret_key: 加密的密鑰
            encrypted_passphrase: 加密的通行短語

        Returns:
            (api_key, secret_key, passphrase)
        """
        return (
            self.decrypt(encrypted_api_key),
            self.decrypt(encrypted_secret_key),
            self.decrypt(encrypted_passphrase),
        )


class KeyGenerator:
    """金鑰生成器"""

    @staticmethod
    def generate_key() -> str:
        """
        生成新的加密金鑰

        Returns:
            Base64 編碼的金鑰字符串
        """
        key = Fernet.generate_key()
        return key.decode()

    @staticmethod
    def derive_key_from_password(password: str, salt: bytes | None = None) -> str:
        """
        從密碼派生金鑰

        Args:
            password: 用戶密碼
            salt: 鹽值（可選，如果不提供會生成新的）

        Returns:
            Base64 編碼的派生金鑰
        """
        if salt is None:
            salt = os.urandom(16)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )

        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key.decode()


def create_encryption_manager(encryption_key: str) -> EncryptionManager:
    """
    創建加密管理器實例

    Args:
        encryption_key: 加密金鑰

    Returns:
        EncryptionManager 實例
    """
    return EncryptionManager(encryption_key)


# 測試函數
def test_encryption():
    """測試加密解密功能"""
    # 生成測試金鑰
    key = KeyGenerator.generate_key()
    print(f"Generated key: {key}")

    # 測試加密
    manager = EncryptionManager(key)

    # 測試數據
    test_api_key = "test_api_key_123"
    test_secret = "test_secret_456"
    test_passphrase = "test_passphrase_789"

    # 加密
    encrypted_credentials = manager.encrypt_api_credentials(test_api_key, test_secret, test_passphrase)
    print("Encrypted credentials:", encrypted_credentials)

    # 解密
    decrypted_credentials = manager.decrypt_api_credentials(*encrypted_credentials)
    print("Decrypted credentials:", decrypted_credentials)

    # 驗證
    assert decrypted_credentials[0] == test_api_key
    assert decrypted_credentials[1] == test_secret
    assert decrypted_credentials[2] == test_passphrase

    print("Encryption test passed!")


if __name__ == "__main__":
    test_encryption()
