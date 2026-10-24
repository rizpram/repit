"""TLS, project restriction, redacted logs and DB/scheduler heartbeat."""
import logging
import os
import re
import ssl
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qsl, urlencode, urlunsplit
PROJECT_REF='lzfrfpokshfrbnbaiuqo'
LOCK_ID=731284910
HEARTBEAT=Path('/tmp/repit-heartbeat')

def database_options(dsn, ca_file):
    uri=urlsplit(dsn)
    host=uri.hostname or ''
    direct=host==f'db.{PROJECT_REF}.supabase.co'
    pooler=host.endswith('.pooler.supabase.com') and unquote(uri.username or '').endswith('.'+PROJECT_REF)
    if uri.scheme not in ('postgres','postgresql') or not (direct or pooler):
        raise ValueError('DATABASE_URL must belong to authorized project')
    if pooler and uri.port!=5432:
        raise ValueError('Use session pooler 5432; transaction pooler cannot hold poller lock')
    if any(k not in ('application_name',) and not k.lower().startswith('ssl') for k,v in parse_qsl(uri.query)):
        raise ValueError('Unsupported DATABASE_URL query parameters')
    query=urlencode([(k,v) for k,v in parse_qsl(uri.query) if not k.lower().startswith('ssl')])
    cleaned=urlunsplit((uri.scheme,uri.netloc,uri.path,query,''))
    ctx=ssl.create_default_context(cafile=ca_file or None)
    ctx.check_hostname=True
    ctx.verify_mode=ssl.CERT_REQUIRED
    return cleaned,ctx

def redact(value):
    value=str(value)
    for key in ('TELEGRAM_BOT_TOKEN','DATABASE_URL','OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY'):
        secret=os.getenv(key)
        if secret:
            value=value.replace(secret,'[REDACTED]')
    value=re.sub(r'postgres(?:ql)?://[^\s"\']+','[REDACTED_DB_URI]',value)
    value=re.sub(r'\b\d{6,}:[A-Za-z0-9_-]{20,}','[REDACTED_TOKEN]',value)
    value=re.sub(r'\bAIza[A-Za-z0-9_-]{30,}','[REDACTED_API_KEY]',value)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}','[REDACTED_API_KEY]',value)

class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))

def setup_logging():
    handler=logging.StreamHandler()
    handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO,handlers=[handler],force=True)
    logging.getLogger('aiogram').setLevel(logging.WARNING)

def healthy(path=HEARTBEAT, now=None):
    try:
        return 0<=(now if now is not None else time.time())-path.stat().st_mtime<120
    except FileNotFoundError:
        return False
