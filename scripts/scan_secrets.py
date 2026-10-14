"""Heuristic secret scan, including all reachable commit versions; no matches printed."""
import re
import subprocess
from pathlib import Path

PATTERNS=[re.compile(r'\b\d{6,}:[A-Za-z0-9_-]{25,}'),
          re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}'),
          re.compile(r'postgres(?:ql)?://[^\s:/]+:([^@\s]+)@')]
def check(name,text):
    if Path(name).name=='.env' or (Path(name).name.startswith('.env.') and Path(name).name!='.env.example'):
        return True
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            if match.lastindex:
                if match[1] in ('replace_locally','ci-only-password'):
                    continue
                if name.startswith('tests/') and match[1] in ('example','password'):
                    continue
            return True
    return False

def scan():
    failures=set()
    commits=subprocess.check_output(['git','rev-list','--all'],text=True).splitlines()
    seen=set()
    for commit in commits:
        entries=subprocess.check_output(['git','ls-tree','-r',commit],text=True).splitlines()
        for entry in entries:
            metadata,name=entry.split('\t',1)
            sha=metadata.split()[2]
            if (sha,name) in seen:
                continue
            seen.add((sha,name))
            text=subprocess.check_output(['git','cat-file','-p',sha]).decode(errors='replace')
            if check(name,text):
                failures.add(name)
    if failures:
        print('Possible secrets in paths:',', '.join(sorted(failures)))
        return 1
    print('No credential patterns or tracked .env detected in reachable commit history (heuristic).')
    return 0

if __name__=='__main__':
    raise SystemExit(scan())
