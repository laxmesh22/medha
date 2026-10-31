-- Referral-code links: only the patient's code can grant access; either side can only END a link.
-- Safe to re-run. Breaks nothing current: the dashboard and the app only read care_links and clinicians and change
-- them through the security-definer functions (link_patient_with_code, create_clinician_profile, ...), which keep
-- working because they run as the table owner.
-- Paste this whole file into the Supabase SQL editor. Do not use the service key from an app.

-- 1. A link can be ended by either side, but not re-activated or moved to another patient/clinician.
--    Re-activating needs the patient to enter the code again (link_patient_with_code = fresh consent).
revoke update on table public.care_links from authenticated;
grant update (status) on table public.care_links to authenticated;
drop policy if exists "clinician ends link" on public.care_links;
create policy "clinician ends link" on public.care_links for update using (clinician_id = my_clinician_id())
  with check (clinician_id = my_clinician_id() and status = 'ended');
drop policy if exists "patient ends link" on public.care_links;
create policy "patient ends link" on public.care_links for update using (patient_id = my_patient_id())
  with check (patient_id = my_patient_id() and status = 'ended');

-- 2. A clinician edits their own details, but cannot verify themselves, pick a referral code, or change who they are.
revoke update on table public.clinicians from authenticated;
grant update (full_name, title, specialization, clinic, city, council, registration_no, years_experience, phone)
  on table public.clinicians to authenticated;

-- 3. A patient sees their clinician's row only while the link is active.
drop policy if exists "patient reads linked clinician" on public.clinicians;
create policy "patient reads linked clinician" on public.clinicians for select using (
  exists (select 1 from care_links l
          where l.clinician_id = clinicians.id and l.patient_id = my_patient_id() and l.status = 'active'));
