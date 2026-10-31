-- Only verified doctors can be linked to patients or see their data.
-- Safe to re-run. Run after 20261031_link_consent_hardening.sql.
-- Paste this whole file into the Supabase SQL editor. Do not use the service key from an app.
--
-- AFTER RUNNING: every doctor still 'pending' loses access to their patients until verified. Verify each real doctor
-- once the team has checked their registration (council + registration number):
--   update public.clinicians set verification_status = 'verified' where email = 'doctor@example.com';

-- Access to patient data needs an active link AND a doctor who is verified now; a rejected doctor loses access at once.
-- Every patient-table policy and publish_care_plan go through this function.
create or replace function public.is_linked_clinician(p uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from care_links l join clinicians c on c.id = l.clinician_id
    where l.patient_id = p and l.clinician_id = my_clinician_id() and l.status = 'active'
      and c.verification_status = 'verified')
$$;

-- A patient can link only to a verified doctor.
create or replace function public.link_patient_with_code(p_code text) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  c uuid;
  v_status text;
  me uuid := my_patient_id();
begin
  if current_sub() is null then raise exception 'not signed in'; end if;
  if me is null then raise exception 'create the patient profile first'; end if;
  select id, verification_status into c, v_status from clinicians where referral_code = upper(trim(p_code));
  if c is null then raise exception 'unknown code'; end if;
  if v_status <> 'verified' then raise exception 'clinician not verified'; end if;
  insert into care_links (patient_id, clinician_id, status, consent_at)
  values (me, c, 'active', now())
  on conflict (patient_id, clinician_id) do update set status = 'active', consent_at = now();
  return c;
end $$;

-- The preview says so too, without showing the unverified doctor's name.
create or replace function public.preview_clinician_by_code(code text)
returns table (full_name text, title text, clinic text, city text)
language plpgsql stable security definer set search_path = public as $$
declare
  v_status text;
begin
  if public.current_sub() is null then
    raise exception 'not signed in';
  end if;
  select c.verification_status into v_status from public.clinicians c where c.referral_code = upper(trim(code));
  if v_status is not null and v_status <> 'verified' then
    raise exception 'clinician not verified';
  end if;
  return query
    select c.full_name, c.title, c.clinic, c.city
    from public.clinicians c
    where c.referral_code = upper(trim(code)) and c.verification_status = 'verified';
end $$;

revoke all on function public.preview_clinician_by_code(text) from public, anon;
grant execute on function public.preview_clinician_by_code(text) to authenticated;
grant execute on function public.link_patient_with_code(text) to authenticated;
