import unittest
from unittest.mock import patch

from app import auth


class VerifyPasswordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hashed = "$2b$12$1nqmxCFIvossKXkg0vvicuKEGDYZUtm1gea3xMN2rf4hZ8alJFvum"

    def test_verify_password_success(self) -> None:
        self.assertTrue(auth.verify_password("Admin#1234", self.hashed))

    def test_verify_password_fallbacks_when_passlib_fails(self) -> None:
        with patch.object(auth.pwd_context, "verify", side_effect=ValueError):
            self.assertTrue(auth.verify_password("Admin#1234", self.hashed))

    def test_verify_password_returns_false_on_invalid_credentials(self) -> None:
        with patch.object(auth.pwd_context, "verify", side_effect=ValueError):
            self.assertFalse(auth.verify_password("wrong", self.hashed))


if __name__ == "__main__":
    unittest.main()
