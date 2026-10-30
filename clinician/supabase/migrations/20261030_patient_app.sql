-- Patient app: intake sync, session flags, and a name preview before linking.
-- Safe to re-run. Does not delete rows or weaken row-level security.
-- Paste this whole file into the Supabase SQL editor. Do not use the service key from an app.

-- Null means the phone could not classify the rep. Existing 0s stay 0.
alter table public.session_exercises alter column reps_rejected drop not null;
alter table public.session_exercises alter column reps_rejected drop default;

-- True when the patient stopped the session before the plan was finished. Null on older rows.
alter table public.sessions add column if not exists ended_early boolean;

-- Everything from the intake that does not already have its own column, plus the app language
-- and text size. The patient can read and update only their own row (policy "patient owns profile").
-- Shape, every key optional:
--   gender, onset, trigger, trigger_note, main_problem, pain_now (number 0-10),
--   sleep, hard_tasks (text[]), load, load_increased, load_note,
--   past_injury, past_injury_when, prior_frozen, seen_before, seen_who (text[]),
--   language ('en' | 'hi'), text_size ('small' | 'medium' | 'large')
-- date_of_birth, sex, affected_side and conditions stay in their own columns.
-- Voice, dark mode and the reminder time stay on the phone.
alter table public.patients add column if not exists intake jsonb not null default '{}'::jsonb;

-- Name, title, clinic and city for a valid referral code. No ids, email or phone.
-- Call it once when the patient submits a code, not on each keystroke.
-- An unknown code returns no row. A missing session raises 'not signed in'.
create or replace function public.preview_clinician_by_code(code text)
returns table (full_name text, title text, clinic text, city text)
language plpgsql stable security definer set search_path = public as $$
begin
  if public.current_sub() is null then
    raise exception 'not signed in';
  end if;
  return query
    select c.full_name, c.title, c.clinic, c.city
    from public.clinicians c
    where c.referral_code = upper(trim(code));
end $$;

revoke all on function public.preview_clinician_by_code(text) from public, anon;
grant execute on function public.preview_clinician_by_code(text) to authenticated;
