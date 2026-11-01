import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from app.webapp_api import create_webapp, validate_init_data


class MiniAppAuthTests(unittest.TestCase):
    def _signed(self, token="123:secret", auth_date=1_800_000_000):
        fields = {
            "auth_date": str(auth_date),
            "query_id": "AAE-test",
            "user": json.dumps({"id": 42, "first_name": "Test"}, separators=(",", ":")),
        }
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(token.encode(), b"WebAppData", hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urlencode(fields)

    def test_valid_telegram_init_data(self):
        user = validate_init_data(self._signed(), "123:secret", now=1_800_000_100)
        self.assertEqual(user["id"], 42)

    def test_rejects_wrong_token(self):
        with self.assertRaises(ValueError):
            validate_init_data(self._signed(), "123:wrong", now=1_800_000_100)

    def test_rejects_expired_auth_date(self):
        with self.assertRaises(ValueError):
            validate_init_data(self._signed(auth_date=1_700_000_000), "123:secret", now=1_800_000_100)

    def test_aiohttp_application_registers_miniapp_routes(self):
        app = create_webapp(None)
        paths = {route.resource.canonical for route in app.router.routes()}
        self.assertIn("/", paths)
        self.assertIn("/api/bootstrap", paths)
        self.assertIn("/api/settings", paths)


if __name__ == "__main__":
    unittest.main()
