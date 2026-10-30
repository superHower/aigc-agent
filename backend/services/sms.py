"""SMS adapters; test delivery writes only to an explicitly configured local directory."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def send_sms(phone: str, purpose: str, code: str, challenge_id: str):
    mode = os.getenv('SMS_MODE', 'disabled')
    if mode == 'test':
        if os.getenv('APP_ENV', 'production') != 'development' or not os.getenv('SMS_TEST_OUTBOX'):
            raise RuntimeError('test SMS requires local development configuration')
        root = Path(os.environ['SMS_TEST_OUTBOX']).resolve()
        media = Path(os.getenv('DATA_DIR', './backend/media')).resolve()
        if root.is_relative_to(media) or media.is_relative_to(root):
            raise RuntimeError('test outbox must be separate from media')
        root.mkdir(parents=True, exist_ok=True)
        path = root / f'{challenge_id}.json'
        # Never return or log the code. This directory must remain outside public media.
        path.write_text(json.dumps({'phone': phone, 'purpose': purpose, 'code': code}), encoding='utf-8')
        return
    if mode != 'http':
        raise RuntimeError('SMS is not configured')
    endpoint = os.getenv('SMS_HTTP_URL', '')
    token = os.getenv('SMS_HTTP_TOKEN', '')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or not token:
        raise RuntimeError('SMS gateway requires HTTPS and credentials')
    body = json.dumps({'phone': phone, 'purpose': purpose, 'code': code, 'request_id': challenge_id}).encode()
    request = Request(endpoint, data=body, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='POST')
    # Gateway must acknowledge only accepted sends; retries are not automatic.
    with urlopen(request, timeout=10) as response:
        if response.status != 200 or json.loads(response.read(4096)).get('accepted') is not True:
            raise RuntimeError('SMS gateway did not accept delivery')
