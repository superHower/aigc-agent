"""Local Windows tunnel launcher; credentials are read from .env, never printed."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
config = dotenv_values(root / '.env')
token = config.get('NATAPP_AUTHTOKEN')
if not token:
    raise SystemExit('NATAPP_AUTHTOKEN is empty in .env')
client = os.getenv('NATAPP_EXE') or shutil.which('natapp') or str(Path.home() / 'natapp.exe')
if not Path(client).is_file():
    raise SystemExit('natapp.exe not found; set NATAPP_EXE or place it in your user directory.')
running = subprocess.run(['powershell', '-NoProfile', '-Command', "@(Get-Process natapp -ErrorAction SilentlyContinue).Count"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
log = root / 'backend' / 'natapp.log'
if running.stdout.strip() == '0':
    log.write_text('', encoding='utf-8')
    subprocess.Popen([client, '-authtoken='+token, '-log='+str(log)], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
for _ in range(40):
    content = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
    urls = re.findall(r'Tunnel established at (https?://[^\s]+)', content)
    if urls:
        print('NATAPP: '+urls[-1])
        break
    time.sleep(.5)
else:
    raise SystemExit('Tunnel address not found. Check backend/natapp.log and NATAPP status.')
