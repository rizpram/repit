import unittest
import ssl
import logging
import os
import tempfile
from pathlib import Path
from datetime import datetime,date,time,timezone,timedelta
from unittest.mock import patch
from app.domain import number,parse_field,parse_meal,parse_workout,reminder_due,week_bounds,validate_vision
from app.security import database_options,SafeFormatter,healthy
from app.goals import calculate_goal

NOW=datetime(2026,10,14,13,tzinfo=timezone.utc)
HEVY='Evening workout 🏋️\nFriday, Oct 09, 2026 at 8:17pm\nBench Press (Smith Machine)\nSet 1: 20 kg x 8\nSet 2: 20,5 kg × 8\n"notes"\nCurl\nSet 1: 20 lb x 10\nPush Up\nSet 1: bodyweight x 12\nSet 2: 12 reps\nhttps://hevy.com/test'

class DomainTests(unittest.TestCase):
    def test_number(self):
        for raw in ['nan','inf','-inf','19','401','abc']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                number(raw,20,400)
        self.assertEqual(number('77,5',20,400),77.5)

    def test_profile(self):
        self.assertEqual(parse_field('birth_date','1988-10-11',NOW.date()),'1988-10-11')
        self.assertIsNone(parse_field('sex_for_bmr','skip'))
        for field,raw in [('birth_date','2015-01-01'),('height_cm','49'),('activity_level','no'),('sex_for_bmr','other')]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                parse_field(field,raw,NOW.date())

    def test_meals(self):
        self.assertEqual(parse_meal('550 35 60 18 Nasi ayam')['description'],'Nasi ayam')
        for raw in ['550.5 35 60 18 meal','10001 0 0 0 meal','500 nan 2 3 meal','500 501 2 3 meal','500 1 2 3']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                parse_meal(raw)
        with self.assertRaises((ValueError,KeyError)):
            validate_vision({})

    def test_hevy(self):
        result=parse_workout(HEVY,'Asia/Jakarta',NOW)
        self.assertEqual(len(result['sets']),5)
        self.assertEqual(result['sets'][0]['exercise_name'],'Bench Press (Smith Machine)')
        self.assertEqual(result['sets'][2]['weight_kg'],9.07)
        self.assertIsNone(result['sets'][3]['weight_kg'])
        self.assertEqual(result['workout_at'].hour,20)
        changed=HEVY.replace('Evening workout 🏋️','New title').replace('20 kg x 8','20.0 KG × 8').replace('"notes"','"other notes"')
        self.assertEqual(result['fingerprint'],parse_workout(changed,'Asia/Jakarta',NOW)['fingerprint'])

    def test_reject_partial_workout(self):
        for raw in ['Workout\nBench\nSet 1: 10 kg x 8\nSet 2: 30s','Workout\nSet 1: 10 kg x 8','Workout\nBench','Workout\nBench\nSet 1: 2 kg x 0']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                parse_workout(raw,'Asia/Jakarta',NOW)

    def test_undated_scope(self):
        raw='Workout\nBench\nSet 1: 10 kg x 8'
        self.assertNotEqual(parse_workout(raw,'Asia/Jakarta',NOW)['fingerprint'],parse_workout(raw,'Asia/Jakarta',NOW+timedelta(days=1))['fingerprint'])

    def test_reminder(self):
        row=dict(timezone='Asia/Jakarta',local_time=time(20),day_of_week=6)
        sunday=datetime(2026,10,18,13,2,tzinfo=timezone.utc)
        self.assertEqual(reminder_due(row,sunday).hour,20)
        self.assertIsNone(reminder_due(row,NOW))
        self.assertIsNone(reminder_due(row,sunday+timedelta(minutes=5)))
        row.update(timezone='Asia/Tokyo',local_time=time(22),day_of_week=None)
        self.assertIsNotNone(reminder_due(row,NOW))
        self.assertEqual(week_bounds(sunday,'Asia/Jakarta')[0],date(2026,10,12))

    def test_tls_project_guard(self):
        dsn,ctx=database_options('postgresql://postgres.lzfrfpokshfrbnbaiuqo:example@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=disable',None)
        self.assertNotIn('sslmode',dsn)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        for dsn in ['postgresql://postgres:example@db.other.supabase.co/postgres','postgresql://postgres.lzfrfpokshfrbnbaiuqo:example@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres']:
            with self.assertRaises(ValueError):
                database_options(dsn,None)

    def test_redaction_and_health(self):
        token='123456789:'+('a'*30)
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':token}):
            record=logging.LogRecord('test',40,'',0,'failure %s postgresql://user:password@host/db',(token,),None)
            output=SafeFormatter().format(record)
            self.assertNotIn(token,output)
            self.assertNotIn('password',output)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'heartbeat'
            self.assertFalse(healthy(p))
            p.touch()
            self.assertTrue(healthy(p))
            self.assertFalse(healthy(p,now=p.stat().st_mtime+121))

    def test_goal_boundaries(self):
        profile=dict(birth_date=date(1988,10,11),sex_for_bmr='male',height_cm=170,current_weight_kg=400,activity_level='active')
        with self.assertRaises(ValueError):
            calculate_goal(profile,'cutting',NOW.date())
        profile.update(current_weight_kg=78,sex_for_bmr=None)
        with self.assertRaises(ValueError):
            calculate_goal(profile,'maintenance',NOW.date())
