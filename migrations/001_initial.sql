-- Apply ONLY to a new dedicated Supabase project.
-- Private schema is not exposed through Supabase Data API.
create schema if not exists fitness;
revoke all on schema fitness from public, anon, authenticated;
create table if not exists fitness.users (
 id bigint generated always as identity primary key,
 telegram_user_id bigint not null unique,
 timezone text not null default 'Asia/Jakarta',
 created_at timestamptz not null default now()
);
create table if not exists fitness.profiles (
 user_id bigint primary key references fitness.users(id) on delete cascade,
 weight_kg numeric(6,2) check(weight_kg > 0),
 height_cm numeric(5,1) check(height_cm > 0),
 age_years integer check(age_years between 13 and 110),
 sex_for_bmr text check(sex_for_bmr in ('male','female')),
 activity_level text check(activity_level in ('sedentary','light','moderate','active')),
 goal_weight_kg numeric(6,2) check(goal_weight_kg > 0),
 daily_calories integer check(daily_calories between 1000 and 6000),
 daily_protein_g integer check(daily_protein_g between 0 and 400),
 updated_at timestamptz not null default now()
);
create table if not exists fitness.reminders (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 kind text not null check(kind in ('morning','lunch','progress','recap','weekly')),
 local_time time not null,
 enabled boolean not null default true,
 unique(user_id,kind)
);
create table if not exists fitness.reminder_deliveries (
 id bigint generated always as identity primary key,
 reminder_id bigint not null references fitness.reminders(id) on delete cascade,
 local_date date not null,
 status text not null default 'pending' check(status in ('pending','sent','failed')),
 sent_at timestamptz,
 unique(reminder_id,local_date)
);
create table if not exists fitness.weight_logs (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 measured_at timestamptz not null default now(),
 weight_kg numeric(6,2) not null check(weight_kg > 0)
);
create table if not exists fitness.food_logs (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 consumed_at timestamptz not null,
 meal_type text not null,
 calories numeric(8,1), protein_g numeric(8,1), carbs_g numeric(8,1), fat_g numeric(8,1),
 source text not null default 'manual', confirmed boolean not null default false,
 created_at timestamptz not null default now()
);
create table if not exists fitness.workout_sessions (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 started_at timestamptz not null,
 source text not null check(source in ('hevy','manual')),
 source_hash text,
 notes text,
 unique(user_id,source_hash)
);
create table if not exists fitness.workout_sets (
 id bigint generated always as identity primary key,
 session_id bigint not null references fitness.workout_sessions(id) on delete cascade,
 exercise_name text not null,
 set_number integer not null check(set_number > 0),
 weight_kg numeric(8,2), reps integer check(reps >= 0)
);
create table if not exists fitness.coach_reports (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 week_ending date not null,
 report_text text not null,
 unique(user_id,week_ending)
);
-- Defense in depth, even though schema is private.
do $$ declare t record; begin
 for t in select tablename from pg_tables where schemaname='fitness' loop
 execute format('alter table fitness.%I enable row level security',t.tablename);
 end loop;
end $$;
