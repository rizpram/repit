"""CI-only rollout safety simulation in disposable container, no Docker socket.

Fake Docker records calls. These are deployment guard tests, never live proof.
Run only inside the explicit isolated CI test container.
"""
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

BASE = Path('/opt/rizpram-fitness-bot')
SHA = 'a' * 40
SCRIPT = Path('/workspace/scripts/deploy.sh')
DOCKER = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['FAKE_LOG'],'a') as log:
    log.write(json.dumps(a)+'\n')
case=os.environ['FAKE_CASE']
if a[:2]==['compose','version']:
    sys.exit(0)
if a and a[0]=='compose':
    if 'config' in a:
        if '--services' in a:
            print('fitness-bot')
        else:
            print(json.dumps({'services':{'fitness-bot':{'read_only':True}}}))
    elif 'build' in a and case=='build_fail':
        sys.exit(3)
    elif 'run' in a and case=='preflight_fail':
        sys.exit(3)
    elif 'up' in a and case=='startup_fail':
        configs=[a[i+1] for i,v in enumerate(a) if v=='-f']
        if any('/releases/' in p for p in configs):
            sys.exit(3)
    elif 'ps' in a:
        print('repit-new-id')
    sys.exit(0)
if a and a[0]=='ps':
    if '-aq' in a and case in ('wrong_owner','startup_fail'):
        print('repit-old-id')
    sys.exit(0)
if a and a[0]=='inspect':
    fmt=a[a.index('--format')+1]
    if 'repit.deployment-test' in fmt:
        sys.exit(1)
    if '.service' in fmt:
        print('fitness-bot')
    elif '.working_dir' in fmt:
        print('/opt/another-app' if case=='wrong_owner' else '/opt/rizpram-fitness-bot')
    elif '.config_files' in fmt:
        print('/opt/rizpram-fitness-bot/docker-compose.yml')
    elif '.Image' in fmt:
        print('sha256:old-tested-image')
    sys.exit(0)
# Disposable DB readiness and test container are simulated.
sys.exit(0)
'''
CURL = r'''#!/usr/bin/env python3
import os,shutil,sys
shutil.copyfile(os.environ['FAKE_ARCHIVE'],sys.argv[sys.argv.index('-o')+1])
'''

class DeployGuardTests(unittest.TestCase):
    def setUp(self):
        if not Path('/.dockerenv').exists() or Path('/var/run/docker.sock').exists():
            self.fail('Run guard simulation only in isolated container without Docker socket')
        if BASE.exists():
            shutil.rmtree(BASE)
        BASE.mkdir(parents=True,mode=0o700)
        (BASE/'.env').write_text('DUMMY_ONLY=1\n')
        (BASE/'.env').chmod(0o600)
        (BASE/'supabase-ca.crt').write_text('-----BEGIN CERTIFICATE-----\ntest-placeholder\n-----END CERTIFICATE-----\n')
        (BASE/'supabase-ca.crt').chmod(0o644)
        (BASE/'docker-compose.yml').write_text('services:\n  fitness-bot:\n    image: old\n')
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        for name,text in [('docker',DOCKER),('curl',CURL)]:
            p=self.root/name
            p.write_text(text)
            p.chmod(0o755)
        if not shutil.which('flock'):
            p=self.root/'flock'
            p.write_text('#!/bin/sh\nexit 0\n')
            p.chmod(0o755)
        self.archive=self.root/'source.tar.gz'
        with tarfile.open(self.archive,'w:gz') as archive:
            payload=b'services:\n  fitness-bot:\n    image: test\n'
            item=tarfile.TarInfo('repit-'+SHA+'/docker-compose.yml')
            item.size=len(payload)
            archive.addfile(item,io.BytesIO(payload))
        self.log=self.root/'calls.jsonl'

    def tearDown(self):
        shutil.rmtree(BASE)
        self.tmp.cleanup()

    def invoke(self,case,sha=SHA):
        env=dict(os.environ,PATH=str(self.root)+os.pathsep+os.environ['PATH'],
                 FAKE_LOG=str(self.log),FAKE_CASE=case,FAKE_ARCHIVE=str(self.archive))
        result=subprocess.run(['bash',str(SCRIPT),sha],env=env,text=True,
                              capture_output=True,timeout=20)
        calls=[json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('VERIFIED_LIVE:',result.stdout)
        return calls

    def assert_no_replacement(self,calls):
        self.assertFalse(any(a and a[0]=='stop' for a in calls))
        self.assertFalse(any(a and a[0]=='compose' and 'up' in a for a in calls))

    def test_invalid_commit_refuses_any_docker_call(self):
        self.assertEqual(self.invoke('invalid','main'),[])

    def test_weak_env_permissions_refuse_replacement(self):
        (BASE/'.env').chmod(0o644)
        self.assert_no_replacement(self.invoke('permissions'))

    def test_unreadable_ca_refuses_before_docker_build(self):
        (BASE/'supabase-ca.crt').chmod(0o600)
        calls=self.invoke('ca_permissions')
        self.assert_no_replacement(calls)
        self.assertFalse(any(a and a[0]=='compose' and 'build' in a for a in calls))

    def test_non_pem_ca_refuses_replacement(self):
        (BASE/'supabase-ca.crt').write_text('not a certificate\n')
        self.assert_no_replacement(self.invoke('ca_format'))

    def test_existing_container_query_ignores_oneoff_runs(self):
        calls=self.invoke('startup_fail')
        query=[a for a in calls if a[:2]==['ps','-aq']]
        self.assertEqual(len(query),1)
        self.assertIn('label=com.docker.compose.oneoff=False',query[0])

    def test_symlink_release_parent_rejected_before_creation(self):
        outside=self.root/'outside'
        outside.mkdir()
        (BASE/'releases').symlink_to(outside)
        self.assert_no_replacement(self.invoke('symlink'))
        self.assertEqual(list(outside.iterdir()),[])

    def test_build_failure_does_not_stop_old_app(self):
        self.assert_no_replacement(self.invoke('build_fail'))

    def test_preflight_failure_does_not_stop_old_app(self):
        self.assert_no_replacement(self.invoke('preflight_fail'))

    def test_unrelated_owner_never_stopped(self):
        self.assert_no_replacement(self.invoke('wrong_owner'))

    def test_startup_failure_restores_only_previous_repit(self):
        calls=self.invoke('startup_fail')
        self.assertEqual([a for a in calls if a and a[0]=='stop'],[['stop','repit-old-id']])
        rollback=[a for a in calls if a and a[0]=='compose' and 'up' in a and any('rollback-' in v for v in a)]
        self.assertEqual(len(rollback),1)
        self.assertIn('fitness-bot',rollback[0])
        self.assertIn('--no-deps',rollback[0])
        self.assertFalse(any(a and a[0]=='restart' for a in calls))

    def test_archive_traversal_is_rejected(self):
        with tarfile.open(self.archive,'w:gz') as archive:
            item=tarfile.TarInfo('repit-'+SHA+'/../../outside.txt')
            item.size=1
            archive.addfile(item,io.BytesIO(b'x'))
        self.assert_no_replacement(self.invoke('archive'))
        self.assertFalse(Path('/opt/outside.txt').exists())

if __name__=='__main__':
    unittest.main(verbosity=2)
