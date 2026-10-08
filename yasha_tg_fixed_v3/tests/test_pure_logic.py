import ast
import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

SERVICES = Path(__file__).parents[1] / 'src' / 'sgugit_bot' / 'services.py'
TREE = ast.parse(SERVICES.read_text(encoding='utf-8'))


def load_function(name, extra=None):
    node = next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    ns = {'re': re, 'hmac': hmac, 'hashlib': hashlib, 'base64': base64, 'Optional': Optional, 'secrets': secrets}
    if extra:
        ns.update(extra)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<test>', 'exec'), ns)
    return ns[name]


def test_referral_roundtrip_and_tamper_rejection():
    secret = b'test-secret'
    signature = load_function('referral_signature', {'SPONSOR_TRACKING_SECRET': secret})
    parse = load_function('parse_referral_arg', {'referral_signature': signature})
    token = f'ref_12345_{signature(12345)}'
    assert parse(token) == 12345
    assert parse(f'ref_12345_{"0"*16}') is None
    assert parse('ref_12345_bad') is None


def test_group_normalization():
    normalize = load_function('normalize_group')
    assert normalize(' ои 11.1 ') == 'ОИ-11.1'
    assert normalize('ОИ-11.1') == 'ОИ-11.1'
    assert normalize('ОИ—11.1') == 'ОИ-11.1'


def test_moderation_rejects_obvious_spam():
    moderation = load_function('moderation_score')
    decision, _ = moderation('announcement', {'text': 'Казино ставки и переводите деньги'})
    assert decision == 'reject'
    decision, _ = moderation('announcement', {'text': 'Важное объявление для группы'})
    assert decision == 'accept'


def test_sponsor_token_is_signed():
    secret = b'test-sponsor-secret'
    def fake_now():
        return datetime.now(timezone.utc)
    token_fn = load_function('sponsor_click_token', {'SPONSOR_TRACKING_SECRET': secret, 'now': fake_now, 'secrets': secrets})
    token = token_fn(777)
    raw, sig = token.split('.', 1)
    payload = base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4))
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()[:32]
    assert hmac.compare_digest(sig, expected)
    assert payload.decode().startswith('777:')


def test_referral_share_url_contains_unique_link():
    signature = load_function('referral_signature', {'SPONSOR_TRACKING_SECRET': b's'})
    referral = load_function('referral_link', {'referral_signature': signature})
    share = load_function('referral_share_url', {'referral_link': referral})
    a = share('example_bot', 1)
    b = share('example_bot', 2)
    assert a != b
    assert 't.me/share/url' in a
    assert 'ref_1_' in a
    assert 'ref_2_' in b


def test_parse_schedule_date_accepts_numeric_and_russian_forms():
    parse = load_function('parse_schedule_date', {'re': re, 'date': __import__('datetime').date})
    today = __import__('datetime').date(2026, 10, 9)
    assert parse('10.10', today) == __import__('datetime').date(2026, 10, 10)
    assert parse('10.10.2026', today) == __import__('datetime').date(2026, 10, 10)
    assert parse('10 октября', today) == __import__('datetime').date(2026, 10, 10)
    assert parse('10 окт', today) == __import__('datetime').date(2026, 10, 10)
    assert parse('10 ноября 2027', today) == __import__('datetime').date(2027, 11, 10)
    assert parse('31.02', today) is None


def test_parse_schedule_date_rolls_year_forward_when_date_has_passed():
    parse = load_function('parse_schedule_date', {'re': re, 'date': __import__('datetime').date})
    today = __import__('datetime').date(2026, 10, 9)
    assert parse('01.10', today) == __import__('datetime').date(2027, 10, 1)
