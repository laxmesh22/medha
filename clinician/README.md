# Physio Buddy · Clinician dashboard

The physiotherapist side of Physio Buddy: onboarding with a referral code, the patients who linked with that code,
care-plan prescribing (versioned), and daily progress (range of motion from the sensors, adherence, pain, form flags).
Video consults included; text messaging is not part of this release.

```bash
cd clinician
npm install
npm run dev          # http://localhost:5175
```

Without Supabase keys it runs on **demo data** (six fictional patients covering the main cases: on track, slow,
nearly full range, rising pain + form issues, missed sessions, new patient without a plan). Plans published in demo mode
are kept in the browser; **Profile → Reset demo data** clears them.

## Video consults
Each patient–clinician link has its own unguessable room (`care_links.video_room`). The clinician starts or books a
call from the patient's **Video calls** tab (or the Overview); the patient app shows booked calls from `video_calls`
and opens the same room. Calls run on **Jitsi Meet** in a new tab: no account for the patient, any phone or laptop,
camera and microphone check before joining. The physio may be asked to sign in once on meet.jit.si to open a room.

- Embedded meet.jit.si calls are cut off after 5 minutes, so the call always opens in its own tab.
- For real patients, point `VITE_VIDEO_BASE_URL` at a self-hosted Jitsi or Jitsi-as-a-Service (8x8) deployment:
  the public meet.jit.si servers are fine for a demo but are not a clinical service.

## Share a preview
`npm run artifact` builds `dist-artifact/physio-buddy-clinician.html`: one self-contained page on demo data
(in-memory routing, no backend access), published as a claude.ai Artifact for the team. Video calls work from it
(they open in a new tab); real patient data needs the deployed app with Supabase.

## Connect Supabase
1. Create a project, open the SQL editor and run `supabase/schema.sql` (tables, row-level security, functions,
   exercise library). Re-running it is safe.
2. Copy `.env.example` to `.env` and fill `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (Settings → API).
3. `npm run dev`, create an account, fill the profile: the referral code is generated on save.

## Data contract with the patient app
Both apps use the same tables (`supabase/schema.sql`). Row-level security means a clinician only ever reads patients
linked to them, and a patient only their own rows.

| Step | Patient app does | Dashboard sees |
|---|---|---|
| Sign up | Supabase Auth, then insert its own `patients` row (`id = auth.uid()`) | nothing yet |
| Link | `rpc('link_patient_with_code', { p_code })` after the patient agrees to share | patient in the list, `consent_at` |
| Plan | read `care_plans` (`status = 'active'`) + `plan_items` | the clinician writes them via `publish_care_plan` |
| Session | insert `sessions` + `session_exercises` after each session | progress charts, adherence, alerts |
| Video call | read `care_links.video_room` + `video_calls` (status `scheduled`); open `https://meet.jit.si/<video_room>` | books calls, starts them, sees past calls |

Session fields the dashboard relies on:

| Field | Meaning |
|---|---|
| `started_at`, `duration_s`, `source` | When, how long, `home` or `station` |
| `pain_before`, `pain_after` | 0–10, patient-reported |
| `session_exercises.peak_deg`, `median_deg` | Degrees from the device geometry (camera skeleton / straps). `null` = unavailable, **never 0**, never typed by the patient |
| `reps_counted`, `reps_rejected` | Reps the coach accepted vs rejected for a compensation |
| `flags` | Compensations seen, e.g. `TRUNK_LEAN_SAGITTAL`, `TRUNK_LEAN_LATERAL`, `ELBOW_DRIFT`, `SHRUG`, `TOO_FAST` |

Exercise ids (`flexion`, `abduction`, `external_rotation`, `internal_rotation`, `pendulum`) are the ones the station's
coach and PB-MotionNet use.

## Rules the dashboard keeps
- Exercise targets and progression are the clinician's: every plan change is a new version; nothing auto-increases.
- Degrees are shown only as measured by the device; missing data shows as "—".
- Alerts: pain ≥ 7 after a recent session (critical), average pain up ≥ 1.5 week-over-week (serious), no session for
  3+ calendar days, more than 25 % of reps rejected, or no plan yet (warning). Thresholds are in `src/lib/stats.ts`
  and are provisional until the clinicians on the team confirm them.

## Design
Off-white and deep teal. The brand values are **provisional**: replace `--brand-offwhite` and `--brand-teal` at the
top of `src/styles.css` with the exact codes from the design. Chart series colours (`--series-1` teal `#00897b`,
`--series-2` orange `#d4612f`) were checked with the dataviz palette validator (chroma, colour-blind separation,
3:1 contrast on the card surface). Status always shows as icon + label + colour.
