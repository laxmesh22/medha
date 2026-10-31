-- Patient app tables: versioned intake, consents, per-patient settings (bridge 039).
-- Already applied on the live project (checked 31 Oct 2026: the tables exist and refuse anonymous reads).
-- Safe to re-run: every statement is "if not exists" / "or replace" / drop-then-create. Rebuilt from schema.sql
-- after this file was overwritten by the SQL editor's warning text. The one-time copy of patients.intake into
-- patient_intake already ran on live and is not repeated here.
-- Paste this whole file into the Supabase SQL editor. Do not use the service key from an app.

-- Versioned intake. A new submit inserts the next version; rows are not updated.
create table if not exists public.patient_intake (
  id               uuid primary key default gen_random_uuid(),
  patient_id       uuid not null references public.patients (id) on delete cascade,
  version          int  not null,
  submitted_at     timestamptz not null default now(),
  date_of_birth    date,
  sex              text check (sex in ('female', 'male', 'other', 'prefer_not_to_say')),
  gender           text,
  affected_side    text check (affected_side in ('left', 'right', 'both')),
  onset            text,
  trigger          text,
  trigger_note     text,
  main_problem     text,
  pain_now         int check (pain_now between 0 and 10),
  sleep            text,
  hard_tasks       text[] not null default '{}',
  load             text,
  load_increased   text,
  load_note        text,
  past_injury      text,
  past_injury_when text,
  prior_frozen     text,
  conditions       text[] not null default '{}',
  seen_before      text,
  seen_who         text[] not null default '{}',
  extra            jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (patient_id, version)
);

create table if not exists public.patient_consents (
  id            uuid primary key default gen_random_uuid(),
  patient_id    uuid not null references public.patients (id) on delete cascade,
  kind          text not null check (kind in ('privacy', 'share_with_clinician')),
  version       text not null,
  agreed_at     timestamptz not null default now(),
  clinician_id  uuid references public.clinicians (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists public.patient_settings (
  patient_id   uuid primary key references public.patients (id) on delete cascade,
  language     text,
  text_size    text check (text_size in ('small', 'medium', 'large')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists sessions_patient_time on public.sessions (patient_id, started_at desc);
create index if not exists video_calls_patient on public.video_calls (patient_id, scheduled_for desc);
create index if not exists care_links_clinician on public.care_links (clinician_id) where status = 'active';
create index if not exists plan_items_plan on public.plan_items (plan_id, position);
create index if not exists patient_intake_patient on public.patient_intake (patient_id, version desc);
create index if not exists patient_consents_patient on public.patient_consents (patient_id, agreed_at desc);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists patient_intake_touch on public.patient_intake;
create trigger patient_intake_touch before update on public.patient_intake
  for each row execute function public.touch_updated_at();
drop trigger if exists patient_consents_touch on public.patient_consents;
create trigger patient_consents_touch before update on public.patient_consents
  for each row execute function public.touch_updated_at();
drop trigger if exists patient_settings_touch on public.patient_settings;
create trigger patient_settings_touch before update on public.patient_settings
  for each row execute function public.touch_updated_at();

alter table public.patient_intake     enable row level security;
alter table public.patient_consents   enable row level security;
alter table public.patient_settings   enable row level security;

drop policy if exists "patient reads intake" on public.patient_intake;
create policy "patient reads intake" on public.patient_intake for select using (patient_id = my_patient_id());
drop policy if exists "patient inserts intake" on public.patient_intake;
create policy "patient inserts intake" on public.patient_intake for insert with check (patient_id = my_patient_id());
drop policy if exists "clinician reads intake" on public.patient_intake;
create policy "clinician reads intake" on public.patient_intake for select using (is_linked_clinician(patient_id));

drop policy if exists "patient reads consents" on public.patient_consents;
create policy "patient reads consents" on public.patient_consents for select using (patient_id = my_patient_id());
drop policy if exists "patient inserts consents" on public.patient_consents;
create policy "patient inserts consents" on public.patient_consents for insert with check (patient_id = my_patient_id());
drop policy if exists "clinician reads consents" on public.patient_consents;
create policy "clinician reads consents" on public.patient_consents for select using (is_linked_clinician(patient_id));

drop policy if exists "patient owns settings" on public.patient_settings;
create policy "patient owns settings" on public.patient_settings for all
  using (patient_id = my_patient_id()) with check (patient_id = my_patient_id());
drop policy if exists "clinician reads settings" on public.patient_settings;
create policy "clinician reads settings" on public.patient_settings for select using (is_linked_clinician(patient_id));

revoke all on table public.patient_intake from public, anon;
revoke all on table public.patient_consents from public, anon;
revoke all on table public.patient_settings from public, anon;
grant select, insert on table public.patient_intake to authenticated;
grant select, insert on table public.patient_consents to authenticated;
grant select, insert, update on table public.patient_settings to authenticated;
