"""Pure validation and Hevy parsing."""
import hashlib
import json
import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

STEPS = [('birth_date','Tanggal lahir (YYYY-MM-DD)?'),('sex_for_bmr','Rumus BMR: male / female / skip (manual)?'),('height_cm','Tinggi (50–250 cm)?'),('current_weight_kg','Berat sekarang (20–400 kg)?'),('target_weight_kg','Target berat (20–400 kg)?'),('activity_level','Aktivitas: sedentary / light / moderate / active / very_active?')]

def number(raw, low, high):
    try:
        value = float(str(raw).replace(',', '.'))
    except (ValueError, TypeError):
        raise ValueError('Angka tidak valid') from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Angka harus {low}–{high}')
    return value

def parse_field(field, raw, today=None):
    if field == 'birth_date':
        value = date.fromisoformat(raw)
        today = today or datetime.now(ZoneInfo('Asia/Jakarta')).date()
        age = today.year-value.year-((today.month,today.day)<(value.month,value.day))
        if not 18 <= age <= 100:
            raise ValueError('Profil otomatis untuk dewasa 18–100 tahun')
        return value.isoformat()
    if field == 'sex_for_bmr':
        if raw == 'skip':
            return None
        if raw not in ('male','female'):
            raise ValueError('Pilih male / female / skip')
        return raw
    if field == 'activity_level':
        if raw not in ('sedentary','light','moderate','active','very_active'):
            raise ValueError('Aktivitas tidak valid')
        return raw
    return number(raw,50 if field=='height_cm' else 20,250 if field=='height_cm' else 400)

def parse_meal(raw):
    parts = raw.split(maxsplit=4)
    if len(parts)!=5 or not parts[4].strip() or len(parts[4])>500:
        raise ValueError('/food 550 35 60 18 Nasi ayam (kcal protein carbs fat deskripsi)')
    kcal = number(parts[0],0,10000)
    if not kcal.is_integer():
        raise ValueError('Kalori harus integer')
    return dict(calories=int(kcal),protein_g=number(parts[1],0,500),carbs_g=number(parts[2],0,1500),fat_g=number(parts[3],0,500),description=parts[4].strip())

def validate_vision(value):
    if not isinstance(value,dict):
        raise ValueError('Respons estimasi tidak valid')
    return parse_meal(' '.join(str(value[k]) for k in ('calories','protein_g','carbs_g','fat_g','description')))

def parse_workout(content, timezone, now):
    """Reject partial imports. Supports kg/lb, decimal comma and bodyweight."""
    if not content.strip() or len(content)>12000:
        raise ValueError('Paste workout (maksimum 12000 karakter)')
    lines=[l.strip() for l in unicodedata.normalize('NFKC',content).splitlines() if l.strip()]
    title, exercise, sets = lines[0][:150], None, []
    workout_at=now.astimezone(ZoneInfo(timezone))
    dated=False
    for i,line in enumerate(lines):
        if re.match(r'^\w+,\s+\w+\s+\d{1,2},\s+\d{4}\s+at\s+',line):
            stamp=re.sub(r'^\w+,\s+','',line)
            stamp=re.sub(r'\s+(am|pm)$',r'\1',stamp,flags=re.I)
            try:
                workout_at=datetime.strptime(stamp,'%b %d, %Y at %I:%M%p').replace(tzinfo=ZoneInfo(timezone))
            except ValueError:
                raise ValueError('Tanggal Hevy tidak terbaca') from None
            dated=True
            continue
        if i==0 or line.startswith(('"', "'", 'http')):
            continue
        m=re.fullmatch(r'Set\s+(\d+|W|D|F):\s*(?:(\d+(?:[.,]\d+)?)\s*(kg|lbs?)\s*[x×]\s*|(?:bodyweight|BW)\s*[x×]\s*)?(\d+)\s*(?:reps)?',line,re.I)
        if m:
            if not exercise:
                raise ValueError('Nama latihan diperlukan')
            weight=number(m[2],0,1500) if m[2] else None
            if weight is not None and m[3].lower().startswith('lb'):
                weight=round(weight*0.45359237,2)
            seq=1+sum(s['exercise_name']==exercise for s in sets)
            sets.append(dict(exercise_name=exercise,set_number=seq,weight_kg=weight,reps=int(number(m[4],1,1000)),raw_line=line))
        elif line.lower().startswith('set '):
            raise ValueError('Set duration/distance belum didukung; tidak ada data disimpan')
        else:
            exercise=line[:150]
    if not sets:
        raise ValueError('Tidak ada strength set terbaca')
    if dated and workout_at>now+timedelta(minutes=5):
        raise ValueError('Tanggal workout di masa depan')
    identity=[workout_at.isoformat() if dated else workout_at.date().isoformat(),[(s['exercise_name'].casefold(),s['weight_kg'],s['reps']) for s in sets]]
    return dict(title=title,workout_at=workout_at,sets=sets,fingerprint=hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest())

def reminder_due(row, now):
    local=now.astimezone(ZoneInfo(row['timezone']))
    if row['day_of_week'] is not None and local.weekday()!=row['day_of_week']:
        return None
    scheduled=datetime.combine(local.date(),row['local_time'],local.tzinfo)
    return scheduled if timedelta(0)<=local-scheduled<timedelta(minutes=5) else None

def week_bounds(now, timezone):
    local=now.astimezone(ZoneInfo(timezone))
    start=local.date()-timedelta(days=local.weekday())
    return start,datetime.combine(start,time(),local.tzinfo),local
