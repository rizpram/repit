-- Applied to rizpram-fitness only. Do not re-run on an already migrated project.
create table if not exists fitness.conversation_states (
 user_id bigint primary key references fitness.users(id) on delete cascade,
 payload jsonb not null,
 updated_at timestamptz not null default now()
);
create table if not exists fitness.food_logs (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 consumed_at timestamptz not null default now(),
 description text not null,
 calories integer not null check(calories between 0 and 10000),
 protein_g numeric(7,1) not null default 0 check(protein_g>=0),
 carbs_g numeric(7,1) not null default 0 check(carbs_g>=0),
 fat_g numeric(7,1) not null default 0 check(fat_g>=0),
 source text not null default 'manual',
 confirmed boolean not null default true,
 created_at timestamptz not null default now()
);
create table if not exists fitness.workout_sessions (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 workout_at timestamptz not null default now(),
 title text not null,
 source text not null default 'manual',
 raw_text text not null,
 fingerprint text not null,
 created_at timestamptz not null default now(),
 unique(user_id,fingerprint)
);
create table if not exists fitness.workout_sets (
 id bigint generated always as identity primary key,
 session_id bigint not null references fitness.workout_sessions(id) on delete cascade,
 exercise_name text not null,
 set_number integer not null check(set_number>0),
 weight_kg numeric(7,2) check(weight_kg>=0),
 reps integer check(reps>=0),
 raw_line text
);
create table if not exists fitness.coach_reports (
 id bigint generated always as identity primary key,
 user_id bigint not null references fitness.users(id) on delete cascade,
 week_start date not null,
 report_text text not null,
 generated_at timestamptz not null default now(),
 unique(user_id,week_start)
);
create unique index if not exists fitness_goals_current_unique on fitness.nutrition_goals(user_id) where effective_to is null;
-- Same-day goal changes are stored as history by closing the previous goal on the current day.
-- Allow zero-length same-day goal validity, since effective_to may equal effective_from.
revoke all on schema fitness from public, anon, authenticated;
do $$ declare t text; begin
 foreach t in array array['conversation_states','food_logs','workout_sessions','workout_sets','coach_reports'] loop
  execute format('alter table fitness.%I enable row level security',t);
 end loop;
end $$;
grant usage on schema fitness to service_role;
grant all on all tables in schema fitness to service_role;
grant usage,select on all sequences in schema fitness to service_role;
