"""Private Telegram fitness assistant: Phase 1 onboarding and goal engine."""
import asyncio
import logging
import json
import hashlib
import re
from datetime import datetime, timedelta
import os
from datetime import date
from zoneinfo import ZoneInfo

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from app.goals import calculate_goal

TZ = ZoneInfo('Asia/Jakarta')
STEPS = [('birth_date', 'Tanggal lahir? (YYYY-MM-DD)'), ('sex_for_bmr', 'Rumus BMR: ketik male atau female (boleh skip untuk target manual)'), ('height_cm', 'Tinggi badan (cm)?'), ('current_weight_kg', 'Berat sekarang (kg)?'), ('target_weight_kg', 'Target berat (kg)?'), ('activity_level', 'Aktivitas: sedentary / light / moderate / active / very_active?')]


def parse_field(field, raw):
    if field == 'birth_date':
        value = date.fromisoformat(raw)
        if value >= date.today() or value.year < 1900:
            raise ValueError('Tanggal lahir tidak valid')
        return value
    if field == 'sex_for_bmr':
        if raw not in ('male', 'female'):
            raise ValueError('Pilih male atau female')
        return raw
    if field == 'activity_level':
        if raw not in ('sedentary', 'light', 'moderate', 'active', 'very_active'):
            raise ValueError('Pilih tingkat aktivitas yang tersedia')
        return raw
    number = float(raw.replace(',', '.'))
    if not 20 <= number <= (250 if field == 'height_cm' else 400):
        raise ValueError('Angka di luar batas wajar')
    return number


async def run():
    token = os.environ['TELEGRAM_BOT_TOKEN']
    allowed = int(os.environ['TELEGRAM_ALLOWED_USER_ID'])
    if not token or token == 'replace_locally' or allowed <= 0:
        raise RuntimeError('Configure private bot credentials locally')
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=3, ssl='require')
    bot, dp = Bot(token), Dispatcher()
    async def load_state(conn, uid):
        return await conn.fetchval('select payload from fitness.conversation_states where user_id=$1', uid) or {}

    async def save_state(conn, uid, state):
        if not state:
            await conn.execute('delete from fitness.conversation_states where user_id=$1',uid)
        else:
            await conn.execute("insert into fitness.conversation_states(user_id,payload) values($1,$2::jsonb) on conflict(user_id) do update set payload=excluded.payload,updated_at=now()",uid,json.dumps(state,default=str))

    async def reminder_loop():
        messages={'morning_goal':'🎯 Target hari ini: /target','lunch':'🍱 Catat makan siang: /food','evening_check':'🏋️ Cek progres: /today','daily_recap':'📊 Rekap: /today','weekly_coach':'📈 Review mingguan: /coach'}
        while True:
            try:
                now=datetime.now(TZ)
                async with pool.acquire() as conn:
                    rows=await conn.fetch('select r.*,u.telegram_user_id from fitness.reminder_settings r join fitness.users u on u.id=r.user_id where r.enabled and u.is_active')
                    for r in rows:
                        if (r['local_time'].hour,r['local_time'].minute)!=(now.hour,now.minute) or (r['day_of_week'] is not None and r['day_of_week']!=now.weekday()):
                            continue
                        row=await conn.fetchrow("insert into fitness.notification_deliveries(user_id,reminder_type,scheduled_for) values($1,$2,$3) on conflict do nothing returning id",r['user_id'],r['reminder_type'],now.replace(second=0,microsecond=0))
                        if row:
                            try:
                                await bot.send_message(r['telegram_user_id'],messages[r['reminder_type']])
                                await conn.execute("update fitness.notification_deliveries set status='sent',delivered_at=now() where id=$1",row['id'])
                            except Exception:
                                logging.exception('Reminder delivery failed')
                                await conn.execute("update fitness.notification_deliveries set status='failed' where id=$1",row['id'])
            except Exception:
                logging.exception('Reminder scheduler error')
            await asyncio.sleep(30)


    async def get_user(conn):
        return await conn.fetchval('''insert into fitness.users (telegram_user_id,timezone)
          values ($1,'Asia/Jakarta') on conflict (telegram_user_id)
          do update set updated_at=now() returning id''', allowed)

    @dp.message()
    async def handler(message: Message):
        if not message.from_user or message.from_user.id != allowed or message.chat.type != 'private':
            return
        raw = (message.text or '').strip()
        cmd = raw.split()[0].split('@')[0].lower() if raw else ''
        try:
            async with pool.acquire() as conn:
                user_id = await get_user(conn)
                state = await load_state(conn,user_id)
                if cmd == '/start':
                    await message.answer('🏋️ REPIT | AI Fitness Coach\n/profile — isi profil\n/goal cutting|bulking|maintenance — pilih tujuan\n/target — target harian\n/weight 78.0 — log berat\n/today — status\n/reminder — jadwal\n/cancel — batalkan input')
                elif cmd == '/cancel':
                    await save_state(conn,user_id,{})
                    await message.answer('Input dibatalkan.')
                elif cmd == '/profile':
                    await save_state(conn,user_id,{'index':0,'data':{},'kind':'profile'})
                    await message.answer('Setup profil. /cancel untuk batal.\n' + STEPS[0][1])
                elif state.get('kind') == 'profile' and not raw.startswith('/'):
                    state = dict(state)
                    field, _ = STEPS[state['index']]
                    try:
                        state['data'][field] = parse_field(field, raw.lower())
                    except (ValueError, OverflowError) as exc:
                        await message.answer(f'Input tidak valid: {exc}. Coba lagi atau /cancel.')
                        return
                    state['index'] += 1
                    await save_state(conn,user_id,state)
                    if state['index'] < len(STEPS):
                        await message.answer(STEPS[state['index']][1])
                    else:
                        d = state['data']
                        await conn.execute('''insert into fitness.user_profiles
                            (user_id,birth_date,sex_for_bmr,height_cm,current_weight_kg,target_weight_kg,activity_level)
                            values($1,$2,$3,$4,$5,$6,$7)
                            on conflict(user_id) do update set birth_date=$2,sex_for_bmr=$3,height_cm=$4,
                            current_weight_kg=$5,target_weight_kg=$6,activity_level=$7,updated_at=now()''',
                            user_id,date.fromisoformat(d['birth_date']),d['sex_for_bmr'],d['height_cm'],d['current_weight_kg'],d['target_weight_kg'],d['activity_level'])
                        await conn.execute('update fitness.users set onboarding_completed=true where id=$1',user_id)
                        await save_state(conn,user_id,{})
                        await message.answer('Profil tersimpan. Ketik /goal cutting, /goal bulking, atau /goal maintenance untuk melihat rekomendasi dan konfirmasi.')
                elif cmd == '/goal':
                    parts = raw.lower().split()
                    if len(parts) != 2 or parts[1] not in ('cutting','bulking','maintenance'):
                        await message.answer('Pilih: /goal cutting, /goal bulking, atau /goal maintenance')
                        return
                    profile = await conn.fetchrow('select * from fitness.user_profiles where user_id=$1',user_id)
                    if not profile:
                        await message.answer('Isi /profile dulu sebelum menentukan goal.')
                        return
                    result = calculate_goal(dict(profile),parts[1],datetime.now(TZ).date())
                    await save_state(conn,user_id,{'kind':'goal','goal':result})
                    await message.answer(f"Mode {parts[1]}\nMaintenance perkiraan: {result['maintenance']} kcal\nTarget: {result['calories']} kcal/hari\nProtein: {result['protein']} g/hari\nEstimasi, bukan angka pasti. Ketik /confirmgoal untuk menyimpan atau /cancel untuk membatalkan.")
                elif cmd == '/confirmgoal':
                    result = state.get('goal')
                    if not result:
                        await message.answer('Belum ada usulan. Gunakan /goal cutting|bulking|maintenance.')
                        return
                    async with conn.transaction():
                        await conn.execute("update fitness.nutrition_goals set effective_to=greatest(effective_from,(now() at time zone 'Asia/Jakarta')::date) where user_id=$1 and effective_to is null",user_id)
                        await conn.execute('''insert into fitness.nutrition_goals
                          (user_id,daily_calories,daily_protein_g,effective_from,goal_mode,calorie_adjustment_pct,estimated_maintenance_kcal,calculation_method,user_confirmed)
                          values($1,$2,$3,(now() at time zone 'Asia/Jakarta')::date,$4,$5,$6,'mifflin_st_jeor',true)''',user_id,result['calories'],result['protein'],result['mode'],result['adjustment'],result['maintenance'])
                    await save_state(conn,user_id,{})
                    await message.answer('✅ Target tersimpan. Lihat /target.')
                elif cmd == '/target':
                    goal = await conn.fetchrow('select goal_mode,daily_calories,daily_protein_g from fitness.nutrition_goals where user_id=$1 and effective_to is null',user_id)
                    await message.answer(f"🎯 {goal['goal_mode']}: {goal['daily_calories']} kcal, protein {goal['daily_protein_g']} g/hari" if goal else 'Belum ada target terkonfirmasi. Mulai /profile dan /goal.')
                elif cmd == '/weight':
                    try:
                        weight = float(raw.split()[1].replace(',','.'))
                        if not 20 <= weight <= 400: raise ValueError()
                    except (IndexError,ValueError):
                        await message.answer('Contoh: /weight 77.5')
                        return
                    await conn.execute('insert into fitness.body_weight_logs(user_id,measured_at,weight_kg) values($1,now(),$2)',user_id,weight)
                    await conn.execute('update fitness.user_profiles set current_weight_kg=$2,updated_at=now() where user_id=$1',user_id,weight)
                    await message.answer(f'⚖️ Berat {weight:g} kg tersimpan dan profil diperbarui.')
                elif cmd == '/food':
                    m=re.fullmatch(r'/food\s+(\d+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+(.+)',raw,re.I|re.S)
                    if not m:
                        await message.answer('Format: /food 550 35 60 18 Nasi ayam (kcal protein carbs fat deskripsi). Nilai manual, bukan AI.');return
                    kcal=int(m[1]); macros=[float(m[i].replace(',','.')) for i in (2,3,4)]
                    if kcal>10000 or any(x<0 or x>1500 for x in macros):
                        await message.answer('Nilai di luar batas.');return
                    await conn.execute('insert into fitness.food_logs(user_id,description,calories,protein_g,carbs_g,fat_g) values($1,$2,$3,$4,$5,$6)',user_id,m[5][:500],kcal,*macros)
                    await message.answer(f'🍽️ {m[5][:100]}: {kcal} kcal, {macros[0]}g protein tercatat.')
                elif cmd == '/workout':
                    content=raw[len('/workout'):].strip()
                    if not content:
                        await message.answer('Paste workout Hevy setelah /workout dalam satu pesan.');return
                    fingerprint=hashlib.sha256(content.lower().encode()).hexdigest()
                    row=await conn.fetchrow("insert into fitness.workout_sessions(user_id,title,source,raw_text,fingerprint) values($1,$2,'hevy_paste',$3,$4) on conflict(user_id,fingerprint) do nothing returning id",user_id,content.splitlines()[0][:150],content,fingerprint)
                    if not row:
                        await message.answer('Workout duplikat sudah tercatat.');return
                    exercise=None;set_no=0;count=0
                    for line in content.splitlines():
                        match=re.search(r'([\d.,]+)\s*kg\s*[x×]\s*(\d+)',line,re.I)
                        if match and exercise:
                            set_no+=1
                            await conn.execute('insert into fitness.workout_sets(session_id,exercise_name,set_number,weight_kg,reps,raw_line) values($1,$2,$3,$4,$5,$6)',row['id'],exercise,set_no,float(match[1].replace(',','.')),int(match[2]),line[:500]);count+=1
                        elif line.strip() and not line.lower().startswith(('set ','http','evening workout','morning workout')) and not match:
                            exercise=line.strip()[:150];set_no=0
                    await message.answer(f'🏋️ Workout tersimpan; {count} set terbaca. Teks asli tersimpan.')
                elif cmd == '/coach':
                    start=datetime.now(TZ).date()-timedelta(days=datetime.now(TZ).weekday())
                    food=await conn.fetchrow("select count(distinct (consumed_at at time zone 'Asia/Jakarta')::date) days,coalesce(sum(calories),0) calories,coalesce(sum(protein_g),0) protein from fitness.food_logs where user_id=$1 and consumed_at >= $2",user_id,start)
                    workouts=await conn.fetchval('select count(*) from fitness.workout_sessions where user_id=$1 and workout_at >= $2',user_id,start)
                    weights=await conn.fetch('select weight_kg from fitness.body_weight_logs where user_id=$1 and measured_at >= $2 order by measured_at',user_id,start)
                    trend=f'{float(weights[-1][0])-float(weights[0][0]):+.2f} kg' if len(weights)>=2 else 'data belum cukup'
                    report=f'📈 REPIT Weekly Review\nHari food log: {food["days"]}/7\nTercatat: {food["calories"]} kcal, {food["protein"]} g protein\nWorkout: {workouts} sesi\nTren berat: {trend}\nHari tanpa log bukan berarti tidak makan. Ini rekap statistik, belum AI Coach.'
                    await conn.execute('insert into fitness.coach_reports(user_id,week_start,report_text) values($1,$2,$3) on conflict(user_id,week_start) do update set report_text=excluded.report_text,generated_at=now()',user_id,start,report)
                    await message.answer(report)
                elif cmd == '/today':
                    weight = await conn.fetchval('select weight_kg from fitness.body_weight_logs where user_id=$1 order by measured_at desc,id desc limit 1',user_id)
                    totals=await conn.fetchrow("select coalesce(sum(calories),0) kcal,coalesce(sum(protein_g),0) protein from fitness.food_logs where user_id=$1 and (consumed_at at time zone 'Asia/Jakarta')::date=(now() at time zone 'Asia/Jakarta')::date",user_id)
                    await message.answer(f'📊 Tercatat: {totals["kcal"]} kcal, protein {totals["protein"]} g. Berat terakhir: {weight if weight is not None else "belum dicatat"} kg.')
                elif cmd == '/reminder':
                    if raw.lower() == '/reminder on':
                        for kind,when,day in [('morning_goal','07:00',None),('lunch','12:00',None),('evening_check','18:00',None),('daily_recap','21:00',None),('weekly_coach','20:00',6)]:
                            await conn.execute('insert into fitness.reminder_settings(user_id,reminder_type,local_time,day_of_week,enabled) values($1,$2,$3::time,$4,true) on conflict(user_id,reminder_type) do update set enabled=true',user_id,kind,when,day)
                        await message.answer('🔔 Reminder aktif: 07,12,18,21 WIB dan Minggu 20 WIB.')
                    elif raw.lower() == '/reminder off':
                        await conn.execute('update fitness.reminder_settings set enabled=false where user_id=$1',user_id)
                        await message.answer('🔕 Reminder nonaktif.')
                    else:
                        await message.answer('Aktifkan: /reminder on; matikan: /reminder off.')
                else:
                    await message.answer('Gunakan /start, /food, /workout, /coach, /reminder on|off. Foto makanan dan AI naratif belum tersedia.')
        except Exception:
            logging.exception('Failed to process Telegram update')
            await message.answer('Terjadi masalah saat memproses pesan. Coba lagi nanti.')

    task=asyncio.create_task(reminder_loop())
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await bot.session.close()
        await pool.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
