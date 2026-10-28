-- Physio Buddy: shared Supabase schema for the clinician dashboard (this app) and the patient app.
-- Run once in the Supabase SQL editor (or `supabase db push`). Safe to re-run: objects are created if missing.
--
-- Who writes what
--   clinician dashboard : clinicians (own row, via create_clinician_profile), care_plans + plan_items, video_calls
--   patient app         : patients (own row), link via link_patient_with_code(code), sessions + session_exercises;
--                         reads its care_links.video_room and video_calls to join consults
--   both read           : exercises (library)
-- Row-level security: a clinician sees only patients linked to them (active care_link); a patient sees only their
-- own rows and their own plans. Degrees in sessions come from the device's geometry, never typed by the patient.
--
-- Sign-in: Auth0 (Google or email) as a Supabase third-party provider, or Supabase's own auth. People are identified
-- by the token's `sub` claim (Auth0 subs such as 'google-oauth2|1234' are not UUIDs, so auth.uid() cannot be used).
-- Auth0 needs a post-login Action that adds the claim role = 'authenticated' to the ID token (see README).

create extension if not exists pgcrypto;

-- The signed-in person's token subject (Auth0 or Supabase auth).
create or replace function public.current_sub() returns text
language sql stable as $$ select coalesce(auth.jwt() ->> 'sub', auth.uid()::text) $$;

-- ------------------------------------------------------------------------------------------- tables
create table if not exists public.clinicians (
  id                   uuid primary key default gen_random_uuid(),
  auth_sub             text not null unique default public.current_sub(),
  email                text,
  full_name            text not null,
  title                text default 'Physiotherapist',
  specialization       text,                 -- e.g. 'Musculoskeletal', 'Sports', 'Neuro'
  clinic               text,
  city                 text,
  council              text,                 -- registering council / association
  registration_no      text,
  years_experience     int check (years_experience between 0 and 70),
  phone                text,
  referral_code        text not null unique,
  verification_status  text not null default 'pending' check (verification_status in ('pending', 'verified', 'rejected')),
  created_at           timestamptz not null default now()
);

create table if not exists public.patients (
  id                   uuid primary key default gen_random_uuid(),
  auth_sub             text not null unique default public.current_sub(),
  full_name            text not null,
  date_of_birth        date,
  sex                  text check (sex in ('female', 'male', 'other', 'prefer_not_to_say')),
  phone                text,
  affected_side        text check (affected_side in ('left', 'right', 'both')),
  dominant_side        text check (dominant_side in ('left', 'right')),
  diagnosis            text,                 -- e.g. 'Adhesive capsulitis (frozen shoulder), freezing phase'
  symptom_onset        date,
  conditions           text[] default '{}',  -- e.g. {'diabetes','hypothyroidism'}
  medications          text,
  notes                text,
  created_at           timestamptz not null default now()
);

create table if not exists public.care_links (
  id              uuid primary key default gen_random_uuid(),
  patient_id      uuid not null references public.patients (id) on delete cascade,
  clinician_id    uuid not null references public.clinicians (id) on delete cascade,
  status          text not null default 'active' check (status in ('active', 'ended')),
  consent_at      timestamptz not null default now(),   -- patient agreed to share their data with this clinician
  created_at      timestamptz not null default now(),
  unique (patient_id, clinician_id)
);

-- Exercise library: the movements the station and straps can measure (ids match the coach / PB-MotionNet classes).
create table if not exists public.exercises (
  id            text primary key,
  name          text not null,
  metric        text not null check (metric in ('elevation', 'rotation')),
  description   text,
  default_sets  int  not null default 2,
  default_reps  int  not null default 10,
  default_hold  int  not null default 3        -- seconds
);

-- A prescription is a versioned care plan; a change creates a new version (the old one is kept as history).
create table if not exists public.care_plans (
  id            uuid primary key default gen_random_uuid(),
  patient_id    uuid not null references public.patients (id) on delete cascade,
  clinician_id  uuid not null references public.clinicians (id),
  version       int  not null,
  status        text not null default 'active' check (status in ('active', 'superseded')),
  notes         text,
  created_at    timestamptz not null default now(),
  unique (patient_id, version)
);

create table if not exists public.plan_items (
  id              uuid primary key default gen_random_uuid(),
  plan_id         uuid not null references public.care_plans (id) on delete cascade,
  exercise_id     text not null references public.exercises (id),
  sets            int  not null check (sets between 1 and 10),
  reps            int  not null check (reps between 1 and 50),
  hold_s          int  not null default 0 check (hold_s between 0 and 120),
  times_per_day   int  not null default 1 check (times_per_day between 1 and 6),
  days_per_week   int  not null default 7 check (days_per_week between 1 and 7),
  rom_target_deg  numeric check (rom_target_deg between 0 and 180),   -- clinician-defined, optional
  pain_stop       int  not null default 6 check (pain_stop between 1 and 10), -- stop the set at this pain (0-10)
  notes           text,
  position        int  not null default 0
);

-- Written by the patient app / clinic station after each session.
create table if not exists public.sessions (
  id            uuid primary key default gen_random_uuid(),
  patient_id    uuid not null references public.patients (id) on delete cascade,
  plan_id       uuid references public.care_plans (id),
  started_at    timestamptz not null,
  duration_s    int  not null check (duration_s >= 0),
  source        text not null default 'home' check (source in ('home', 'station')),
  pain_before   int  check (pain_before between 0 and 10),
  pain_after    int  check (pain_after between 0 and 10),
  notes         text
);

create table if not exists public.session_exercises (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references public.sessions (id) on delete cascade,
  exercise_id    text not null references public.exercises (id),
  reps_counted   int  not null default 0,     -- reps the coach accepted
  reps_rejected  int  not null default 0,     -- reps with a compensation or out of the movement
  peak_deg       numeric,                     -- best rep (geometry); null = unavailable, never 0
  median_deg     numeric,
  flags          text[] default '{}'          -- e.g. {'TRUNK_LEAN_LATERAL','ELBOW_DRIFT'}
);

-- Video consults. Each care link has its own unguessable room name; the call itself runs on the video provider
-- (Jitsi Meet by default, VITE_VIDEO_BASE_URL in the apps). Both apps open https://<provider>/<video_room>.
alter table public.care_links add column if not exists video_room text not null
  default ('pb-' || encode(gen_random_bytes(9), 'hex'));

create table if not exists public.video_calls (
  id             uuid primary key default gen_random_uuid(),
  patient_id     uuid not null references public.patients (id) on delete cascade,
  clinician_id   uuid not null references public.clinicians (id) on delete cascade,
  scheduled_for  timestamptz,                 -- null = started straight away
  duration_min   int  not null default 15 check (duration_min between 5 and 120),
  status         text not null default 'scheduled' check (status in ('scheduled', 'started', 'cancelled')),
  started_at     timestamptz,
  notes          text,
  created_at     timestamptz not null default now()
);

create index if not exists sessions_patient_time on public.sessions (patient_id, started_at desc);
create index if not exists video_calls_patient on public.video_calls (patient_id, scheduled_for desc);
create index if not exists care_links_clinician on public.care_links (clinician_id) where status = 'active';
create index if not exists plan_items_plan on public.plan_items (plan_id, position);

-- ------------------------------------------------------------------------------------------- helpers
create or replace function public.my_clinician_id() returns uuid
language sql stable security definer set search_path = public as $$
  select id from clinicians where auth_sub = current_sub()
$$;

create or replace function public.my_patient_id() returns uuid
language sql stable security definer set search_path = public as $$
  select id from patients where auth_sub = current_sub()
$$;

create or replace function public.is_linked_clinician(p uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from care_links where patient_id = p and clinician_id = my_clinician_id() and status = 'active')
$$;

-- 8-character referral code without look-alike characters (no 0/O, 1/I/L)
create or replace function public.new_referral_code() returns text
language plpgsql volatile set search_path = public as $$
declare
  alphabet text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  code text;
begin
  loop
    code := 'PB-';
    for i in 1..6 loop
      code := code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    exit when not exists (select 1 from clinicians where referral_code = code);
  end loop;
  return code;
end $$;

-- Doctor sign-up / profile edit: creates (or updates) the caller's clinician row and returns it. The referral code is
-- created on first save; verification_status stays 'pending' until the team checks the registration.
create or replace function public.create_clinician_profile(p jsonb) returns public.clinicians
language plpgsql security definer set search_path = public as $$
declare
  row clinicians;
begin
  if current_sub() is null then raise exception 'not signed in'; end if;
  if coalesce(trim(p->>'full_name'), '') = '' then raise exception 'full name is required'; end if;
  insert into clinicians (auth_sub, email, full_name, title, specialization, clinic, city, council, registration_no,
                          years_experience, phone, referral_code)
  values (current_sub(), auth.jwt() ->> 'email', p->>'full_name', coalesce(nullif(p->>'title', ''), 'Physiotherapist'),
          p->>'specialization', p->>'clinic', p->>'city', p->>'council', p->>'registration_no',
          nullif(p->>'years_experience', '')::int, p->>'phone', new_referral_code())
  on conflict (auth_sub) do update set
    full_name = excluded.full_name, title = excluded.title, specialization = excluded.specialization,
    clinic = excluded.clinic, city = excluded.city, council = excluded.council, registration_no = excluded.registration_no,
    years_experience = excluded.years_experience, phone = excluded.phone, email = coalesce(excluded.email, clinicians.email)
  returning * into row;
  return row;
end $$;

create or replace function public.regenerate_referral_code() returns text
language plpgsql security definer set search_path = public as $$
declare
  code text := new_referral_code();
begin
  update clinicians set referral_code = code where auth_sub = current_sub();
  if not found then raise exception 'no clinician profile'; end if;
  return code;
end $$;

-- Patient app: link the signed-in patient to the clinician who owns the code (the patient consents by calling it).
create or replace function public.link_patient_with_code(p_code text) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  c uuid;
  me uuid := my_patient_id();
begin
  if current_sub() is null then raise exception 'not signed in'; end if;
  if me is null then raise exception 'create the patient profile first'; end if;
  select id into c from clinicians where referral_code = upper(trim(p_code));
  if c is null then raise exception 'unknown code'; end if;
  insert into care_links (patient_id, clinician_id, status, consent_at)
  values (me, c, 'active', now())
  on conflict (patient_id, clinician_id) do update set status = 'active', consent_at = now();
  return c;
end $$;

-- Clinician: publish a new care-plan version (items as JSON) and supersede the previous one, atomically.
create or replace function public.publish_care_plan(p_patient uuid, p_notes text, p_items jsonb) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v int;
  plan uuid;
  it jsonb;
  pos int := 0;
begin
  if not is_linked_clinician(p_patient) then raise exception 'not your patient'; end if;
  select coalesce(max(version), 0) + 1 into v from care_plans where patient_id = p_patient;
  update care_plans set status = 'superseded' where patient_id = p_patient and status = 'active';
  insert into care_plans (patient_id, clinician_id, version, status, notes)
  values (p_patient, my_clinician_id(), v, 'active', p_notes) returning id into plan;
  for it in select * from jsonb_array_elements(p_items) loop
    insert into plan_items (plan_id, exercise_id, sets, reps, hold_s, times_per_day, days_per_week, rom_target_deg,
                            pain_stop, notes, position)
    values (plan, it->>'exercise_id', (it->>'sets')::int, (it->>'reps')::int, coalesce((it->>'hold_s')::int, 0),
            coalesce((it->>'times_per_day')::int, 1), coalesce((it->>'days_per_week')::int, 7),
            nullif(it->>'rom_target_deg', '')::numeric, coalesce((it->>'pain_stop')::int, 6), it->>'notes', pos);
    pos := pos + 1;
  end loop;
  return plan;
end $$;

-- ------------------------------------------------------------------------------------------- row-level security
alter table public.clinicians        enable row level security;
alter table public.patients          enable row level security;
alter table public.care_links        enable row level security;
alter table public.exercises         enable row level security;
alter table public.care_plans        enable row level security;
alter table public.plan_items        enable row level security;
alter table public.sessions          enable row level security;
alter table public.session_exercises enable row level security;
alter table public.video_calls       enable row level security;

drop policy if exists "clinician reads own" on public.clinicians;
create policy "clinician reads own" on public.clinicians for select using (auth_sub = current_sub());
drop policy if exists "clinician updates own" on public.clinicians;
create policy "clinician updates own" on public.clinicians for update using (auth_sub = current_sub())
  with check (auth_sub = current_sub());
drop policy if exists "patient reads linked clinician" on public.clinicians;
create policy "patient reads linked clinician" on public.clinicians for select using (
  exists (select 1 from care_links l where l.clinician_id = clinicians.id and l.patient_id = my_patient_id()));

drop policy if exists "patient owns profile" on public.patients;
create policy "patient owns profile" on public.patients for all using (auth_sub = current_sub())
  with check (auth_sub = current_sub());
drop policy if exists "clinician reads linked patients" on public.patients;
create policy "clinician reads linked patients" on public.patients for select using (is_linked_clinician(id));

drop policy if exists "link parties read" on public.care_links;
create policy "link parties read" on public.care_links for select
  using (patient_id = my_patient_id() or clinician_id = my_clinician_id());
drop policy if exists "clinician ends link" on public.care_links;
create policy "clinician ends link" on public.care_links for update using (clinician_id = my_clinician_id())
  with check (clinician_id = my_clinician_id());
drop policy if exists "patient ends link" on public.care_links;
create policy "patient ends link" on public.care_links for update using (patient_id = my_patient_id())
  with check (patient_id = my_patient_id());

drop policy if exists "library readable" on public.exercises;
create policy "library readable" on public.exercises for select using (auth.role() = 'authenticated');

drop policy if exists "plans readable" on public.care_plans;
create policy "plans readable" on public.care_plans for select
  using (patient_id = my_patient_id() or is_linked_clinician(patient_id));
drop policy if exists "plan items readable" on public.plan_items;
create policy "plan items readable" on public.plan_items for select using (
  exists (select 1 from care_plans p where p.id = plan_items.plan_id
          and (p.patient_id = my_patient_id() or is_linked_clinician(p.patient_id))));

drop policy if exists "patient writes sessions" on public.sessions;
create policy "patient writes sessions" on public.sessions for insert with check (patient_id = my_patient_id());
drop policy if exists "sessions readable" on public.sessions;
create policy "sessions readable" on public.sessions for select
  using (patient_id = my_patient_id() or is_linked_clinician(patient_id));
drop policy if exists "patient writes session exercises" on public.session_exercises;
create policy "patient writes session exercises" on public.session_exercises for insert with check (
  exists (select 1 from sessions s where s.id = session_exercises.session_id and s.patient_id = my_patient_id()));
drop policy if exists "session exercises readable" on public.session_exercises;
create policy "session exercises readable" on public.session_exercises for select using (
  exists (select 1 from sessions s where s.id = session_exercises.session_id
          and (s.patient_id = my_patient_id() or is_linked_clinician(s.patient_id))));

drop policy if exists "call parties read" on public.video_calls;
create policy "call parties read" on public.video_calls for select
  using (patient_id = my_patient_id() or clinician_id = my_clinician_id());
drop policy if exists "clinician books calls" on public.video_calls;
create policy "clinician books calls" on public.video_calls for insert
  with check (clinician_id = my_clinician_id() and is_linked_clinician(patient_id));
drop policy if exists "clinician updates calls" on public.video_calls;
create policy "clinician updates calls" on public.video_calls for update using (clinician_id = my_clinician_id())
  with check (clinician_id = my_clinician_id());

grant execute on function public.create_clinician_profile(jsonb) to authenticated;
grant execute on function public.regenerate_referral_code() to authenticated;
grant execute on function public.link_patient_with_code(text) to authenticated;
grant execute on function public.publish_care_plan(uuid, text, jsonb) to authenticated;

-- ------------------------------------------------------------------------------------------- library seed
insert into public.exercises (id, name, metric, description, default_sets, default_reps, default_hold) values
  ('flexion', 'Forward raise (flexion)', 'elevation', 'Raise the straight arm forward and up, thumb leading.', 2, 10, 3),
  ('abduction', 'Side raise (abduction)', 'elevation', 'Raise the straight arm out to the side, palm down.', 2, 10, 3),
  ('external_rotation', 'Outward rotation', 'rotation', 'Elbow at the side, bent 90 deg; swing the forearm out.', 2, 10, 3),
  ('internal_rotation', 'Inward rotation', 'rotation', 'Elbow at the side, bent 90 deg; swing the forearm in.', 2, 10, 3),
  ('pendulum', 'Pendulum', 'elevation', 'Lean forward, let the arm hang and swing it in small circles.', 2, 10, 0)
on conflict (id) do nothing;
