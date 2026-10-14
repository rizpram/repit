"""Atomic command processing. Telegram sends occur only after commit."""
import json
import hashlib
from datetime import date, time
from zoneinfo import ZoneInfo
from app.domain import STEPS, number, parse_field, parse_meal, parse_workout, week_bounds
from app.goals import calculate_goal

HELP=('REPIT — rekap deterministik, bukan AI Coach\n/profile — setup\n'
      '/goal cutting|bulking|maintenance\n/goal manual 2000 140\n/confirmgoal\n/target\n'
      '/weight 77.5\n/food 550 35 60 18 Nasi ayam\n/confirmfood — simpan estimasi foto\n'
      '/workout — paste Hevy setelah perintah\n/coach\n/today\n'
      '/reminder on|off — opt-in\n/timezone Asia/Jakarta\n/cancel')

async def load_state(conn,uid):
    value=await conn.fetchval('select payload from fitness.conversation_states where user_id=$1',uid)
    return json.loads(value) if isinstance(value,str) else (value or {})

async def save_state(conn,uid,state):
    if state:
        await conn.execute('''insert into fitness.conversation_states(user_id,payload)
            values($1,$2::jsonb) on conflict(user_id) do update
            set payload=excluded.payload,updated_at=now()''',uid,json.dumps(state))
    else:
        await conn.execute('delete from fitness.conversation_states where user_id=$1',uid)

async def coach(conn,uid,now,timezone):
    start,lower,upper=week_bounds(now,timezone)
    food=await conn.fetchrow('''select count(distinct (consumed_at at time zone $4)::date) days,
        coalesce(sum(calories),0) calories,coalesce(sum(protein_g),0) protein
        from fitness.food_logs where user_id=$1 and confirmed and consumed_at >= $2 and consumed_at <= $3''',uid,lower,upper,timezone)
    workouts=await conn.fetchval('select count(*) from fitness.workout_sessions where user_id=$1 and workout_at >= $2 and workout_at <= $3',uid,lower,upper)
    weights=await conn.fetch('select weight_kg from fitness.body_weight_logs where user_id=$1 and measured_at >= $2 and measured_at <= $3 order by measured_at,id',uid,lower,upper)
    trend=f'{float(weights[-1][0])-float(weights[0][0]):+.2f} kg' if len(weights)>=2 else 'data belum cukup'
    report=(f'REPIT Weekly Review — deterministik, bukan AI\nMinggu mulai {start}\n'
            f'Hari food log: {food["days"]}/7\nTercatat: {food["calories"]} kcal, {food["protein"]} g protein\n'
            f'Workout: {workouts} sesi\nTren berat: {trend}\nHari tanpa log bukan berarti tidak makan.')
    await conn.execute('''insert into fitness.coach_reports(user_id,week_start,report_text)
        values($1,$2,$3) on conflict(user_id,week_start) do update
        set report_text=excluded.report_text,generated_at=now()''',uid,start,report)
    return report

async def store_meal(conn,uid,meal,source='manual'):
    await conn.execute('''insert into fitness.food_logs
        (user_id,description,calories,protein_g,carbs_g,fat_g,source,confirmed)
        values($1,$2,$3,$4,$5,$6,$7,true)''',uid,meal['description'],meal['calories'],meal['protein_g'],meal['carbs_g'],meal['fat_g'],source)

async def command(conn,uid,raw,now,timezone):
    state=await load_state(conn,uid)
    parts=raw.split(maxsplit=1)
    cmd=parts[0].split('@')[0].lower() if parts else ''
    arg=parts[1].strip() if len(parts)>1 else ''
    today=now.astimezone(ZoneInfo(timezone)).date()
    if cmd=='/start':
        return HELP+('\nSetup profil masih berlangsung. Lanjut jawab atau /cancel.' if state.get('kind')=='profile' else '')
    if cmd=='/cancel':
        await save_state(conn,uid,{})
        return 'Input dibatalkan.'
    if cmd=='/profile':
        if state.get('kind')!='profile':
            state=dict(kind='profile',index=0,data={})
            await save_state(conn,uid,state)
        return 'Setup profil. /cancel untuk batal.\n'+STEPS[state['index']][1]
    if state.get('kind')=='profile' and not raw.startswith('/'):
        field=STEPS[state['index']][0]
        state['data'][field]=parse_field(field,raw.lower(),today)
        state['index']+=1
        if state['index']<len(STEPS):
            await save_state(conn,uid,state)
            return STEPS[state['index']][1]
        d=state['data']
        await conn.execute('''insert into fitness.user_profiles
            (user_id,birth_date,sex_for_bmr,height_cm,current_weight_kg,target_weight_kg,activity_level)
            values($1,$2,$3,$4,$5,$6,$7) on conflict(user_id) do update set
            birth_date=$2,sex_for_bmr=$3,height_cm=$4,current_weight_kg=$5,
            target_weight_kg=$6,activity_level=$7,updated_at=now()''',uid,date.fromisoformat(d['birth_date']),d['sex_for_bmr'],d['height_cm'],d['current_weight_kg'],d['target_weight_kg'],d['activity_level'])
        await conn.execute('insert into fitness.body_weight_logs(user_id,measured_at,weight_kg) values($1,$2,$3)',uid,now,d['current_weight_kg'])
        await conn.execute('update fitness.users set onboarding_completed=true where id=$1',uid)
        await save_state(conn,uid,{})
        return 'Profil tersimpan. Pilih /goal cutting|bulking|maintenance atau /goal manual 2000 140.'
    if cmd=='/goal':
        args=arg.lower().split()
        if len(args)==3 and args[0]=='manual':
            kcal=number(args[1],800,10000)
            if not kcal.is_integer():
                raise ValueError('Kalori harus integer')
            result=dict(mode='maintenance',calories=int(kcal),protein=number(args[2],0,500),adjustment=0,maintenance=None,method='manual')
        elif len(args)==1 and args[0] in ('cutting','bulking','maintenance'):
            profile=await conn.fetchrow('select * from fitness.user_profiles where user_id=$1',uid)
            if not profile or not profile['birth_date']:
                return 'Isi /profile dulu.'
            result=calculate_goal(dict(profile),args[0],today)
            result['method']='mifflin_st_jeor'
        else:
            raise ValueError('/goal cutting|bulking|maintenance atau /goal manual 2000 140')
        await save_state(conn,uid,dict(kind='goal',goal=result))
        return f"Usulan {result['mode']}: {result['calories']} kcal, {result['protein']} g protein/hari.\nEstimasi. /confirmgoal untuk simpan; /cancel untuk batal."
    if cmd=='/confirmgoal':
        result=state.get('goal') if state.get('kind')=='goal' else None
        if not result:
            return 'Belum ada usulan. Gunakan /goal.'
        # Half-open [from,to); retain zero-length rows for same-day history.
        await conn.execute('''update fitness.nutrition_goals set effective_to=greatest(effective_from,$2)
            where user_id=$1 and effective_to is null''',uid,today)
        await conn.execute('''insert into fitness.nutrition_goals
            (user_id,daily_calories,daily_protein_g,effective_from,goal_mode,
             calorie_adjustment_pct,estimated_maintenance_kcal,calculation_method,user_confirmed)
            values($1,$2,$3,$4,$5,$6,$7,$8,true)''',uid,result['calories'],result['protein'],today,result['mode'],result['adjustment'],result['maintenance'],result.get('method','mifflin_st_jeor'))
        await save_state(conn,uid,{})
        return 'Target tersimpan. Lihat /target.'
    if cmd=='/target':
        goal=await conn.fetchrow('''select * from fitness.nutrition_goals where user_id=$1 and effective_from <= $2
            and (effective_to is null or effective_to > $2) order by effective_from desc,id desc limit 1''',uid,today)
        return f"{goal['goal_mode']}: {goal['daily_calories']} kcal, protein {goal['daily_protein_g']} g/hari" if goal else 'Belum ada target terkonfirmasi. Gunakan /goal.'
    if cmd=='/weight':
        weight=number(arg,20,400)
        await conn.execute('insert into fitness.body_weight_logs(user_id,measured_at,weight_kg) values($1,$2,$3)',uid,now,weight)
        await conn.execute('''insert into fitness.user_profiles(user_id,current_weight_kg) values($1,$2)
            on conflict(user_id) do update set current_weight_kg=$2,updated_at=now()''',uid,weight)
        if state.get('kind')=='profile':
            state['data']['current_weight_kg']=weight
            await save_state(conn,uid,state)
        elif state.get('kind')=='goal':
            await save_state(conn,uid,{})
        return f'Berat {weight:g} kg tersimpan dan profil diperbarui. Usulan goal dibatalkan; target aktif tetap.'
    if cmd=='/food':
        meal=parse_meal(arg)
        await store_meal(conn,uid,meal)
        return f"{meal['description']}: {meal['calories']} kcal tercatat (manual, bukan AI)."
    if cmd=='/confirmfood':
        if state.get('kind')!='meal':
            return 'Belum ada estimasi foto untuk dikonfirmasi.'
        await store_meal(conn,uid,state['meal'],'photo_estimate')
        await save_state(conn,uid,{})
        return 'Estimasi makanan dikonfirmasi dan dicatat.'
    if cmd=='/workout':
        workout=parse_workout(arg,timezone,now)
        # Exact Phase 1.2 legacy fingerprints still deduplicate existing imports.
        legacy=hashlib.sha256(arg.lower().encode()).hexdigest()
        if await conn.fetchval('select id from fitness.workout_sessions where user_id=$1 and fingerprint=$2',uid,legacy):
            return 'Workout duplikat sudah tercatat.'
        sid=await conn.fetchval('''insert into fitness.workout_sessions
            (user_id,title,source,raw_text,fingerprint,workout_at) values($1,$2,'hevy_paste',$3,$4,$5)
            on conflict(user_id,fingerprint) do nothing returning id''',uid,workout['title'],arg,workout['fingerprint'],workout['workout_at'])
        if sid is None:
            return 'Workout duplikat sudah tercatat.'
        for s in workout['sets']:
            await conn.execute('''insert into fitness.workout_sets
                (session_id,exercise_name,set_number,weight_kg,reps,raw_line) values($1,$2,$3,$4,$5,$6)''',sid,s['exercise_name'],s['set_number'],s['weight_kg'],s['reps'],s['raw_line'])
        return f"Workout tersimpan: {len(workout['sets'])} set."
    if cmd=='/coach':
        return await coach(conn,uid,now,timezone)
    if cmd=='/today':
        totals=await conn.fetchrow('''select coalesce(sum(calories),0) kcal,coalesce(sum(protein_g),0) protein
            from fitness.food_logs where user_id=$1 and confirmed and (consumed_at at time zone $2)::date=$3''',uid,timezone,today)
        return f"Tercatat: {totals['kcal']} kcal, {totals['protein']} g protein."
    if cmd=='/timezone':
        try:
            ZoneInfo(arg)
        except (KeyError,ValueError):
            raise ValueError('Gunakan zona IANA, misalnya Asia/Jakarta') from None
        await conn.execute('update fitness.users set timezone=$2 where id=$1',uid,arg)
        return f'Zona waktu: {arg}. Harian mengikuti zona ini; coach Minggu 20:00 Asia/Jakarta.'
    if cmd=='/reminder':
        if arg.lower()=='on':
            for kind,clock,day in [('morning_goal',time(7),None),('lunch',time(12),None),('evening_check',time(18),None),('daily_recap',time(21),None),('weekly_coach',time(20),6)]:
                await conn.execute('''insert into fitness.reminder_settings(user_id,reminder_type,local_time,day_of_week,enabled)
                    values($1,$2,$3,$4,true) on conflict(user_id,reminder_type) do update
                    set enabled=true,local_time=excluded.local_time,day_of_week=excluded.day_of_week''',uid,kind,clock,day)
            return 'Reminder aktif: 07,12,18,21 zona profil; coach Minggu 20:00 Asia/Jakarta.'
        if arg.lower()=='off':
            await conn.execute('update fitness.reminder_settings set enabled=false where user_id=$1',uid)
            return 'Reminder nonaktif.'
        return 'Opt-in: /reminder on; matikan: /reminder off.'
    return 'Gunakan /start untuk daftar perintah.'

async def process(conn,update_id,telegram_id,chat_id,raw,now,vision=None):
    """Atomic dedup and mutations. Unexpected failure rolls everything back."""
    async with conn.transaction():
        claimed=await conn.fetchval('''insert into fitness.bot_events(telegram_update_id,event_type)
            values($1,'message') on conflict(telegram_update_id) do nothing returning id''',update_id)
        if claimed is None:
            return None
        uid=await conn.fetchval('''insert into fitness.users(telegram_user_id,telegram_chat_id) values($1,$2)
            on conflict(telegram_user_id) do update set telegram_chat_id=$2,updated_at=now() returning id''',telegram_id,chat_id)
        await conn.execute('select pg_advisory_xact_lock($1)',uid)
        timezone=await conn.fetchval('select timezone from fitness.users where id=$1',uid)
        try:
            async with conn.transaction():
                if vision is not None:
                    if isinstance(vision,str):
                        reply=vision
                    else:
                        state=await load_state(conn,uid)
                        if state.get('kind') in ('profile','goal'):
                            reply='Selesaikan input aktif atau /cancel sebelum foto.'
                        else:
                            await save_state(conn,uid,dict(kind='meal',meal=vision))
                            reply=(f"Estimasi AI foto: {vision['description']}\n{vision['calories']} kcal; protein {vision['protein_g']} g, carbs {vision['carbs_g']} g, fat {vision['fat_g']} g.\n"
                                   'Belum dicatat. /confirmfood untuk simpan; /cancel untuk batal.\nKoreksi: /cancel lalu /food manual.')
                else:
                    reply=await command(conn,uid,raw,now,timezone)
        except (ValueError,KeyError,OverflowError):
            reply='Input tidak valid. Periksa format di /start atau /cancel.'
        await conn.execute("update fitness.bot_events set user_id=$2,status='processed' where id=$1",claimed,uid)
    return reply
