"""Credential-free proof of polling, DB access and command replies."""
import json
import time
from pathlib import Path
PATH = Path('/tmp/repit-runtime.json')
STATE = {}

def mark(event, command=None, path=PATH, now=None):
    stamp = time.time() if now is None else now
    STATE.setdefault('started_at', stamp)
    STATE[event] = stamp
    if command in ('/start','/profile','/goal','/confirmgoal','/target','/weight',
                   '/food','/confirmfood','/workout','/reminder','/coach','/today','/timezone','/cancel'):
        STATE.setdefault('command_replies', {})[command] = stamp
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(STATE), encoding='utf-8')
    temporary.replace(path)

async def record_request(make_request, bot, method):
    result = await make_request(bot, method)
    if getattr(method, '__api_method__', '') == 'getUpdates':
        mark('last_poll_success')
    return result

def evidence(value, now=None, require_commands=False):
    now = time.time() if now is None else now
    result = {}
    for key in ('last_db_success', 'last_poll_success'):
        stamp = value.get(key)
        result[key] = isinstance(stamp, (int,float)) and 0 <= now - stamp < 120
    commands = value.get('command_replies', {})
    started = value.get('started_at', 0)
    for name, command in (('start_reply','/start'), ('target_reply','/target')):
        stamp = commands.get(command, 0)
        result[name] = isinstance(stamp, (int,float)) and isinstance(started, (int,float)) and 0 < started <= stamp <= now
    result['verified'] = all(result[k] for k in ('last_db_success','last_poll_success'))
    if require_commands:
        result['verified'] = result['verified'] and result['start_reply'] and result['target_reply']
    return result

if __name__ == '__main__':
    import sys
    try:
        result = evidence(json.loads(PATH.read_text()), require_commands='--require-commands' in sys.argv)
        print(json.dumps(result))
        raise SystemExit(0 if result['verified'] else 1)
    except (OSError,ValueError,TypeError):
        print('{"verified": false, "reason": "runtime evidence unavailable"}')
        raise SystemExit(1) from None
