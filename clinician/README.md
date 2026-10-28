# Auri · Clinician dashboard

The physiotherapist side of Auri: onboarding with a referral code, the patients who linked with that code,
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

## Sign-in and doctor sign-up
- **Sign in** (`/login`): *Continue with Google* or *Continue with email*.
- **New doctor sign-up** (`/signup`), three steps:
  1. Account: Google or email.
  2. Professional details: name, qualification, specialisation, clinic, city, registering council, registration
     number, experience, phone.
  3. Confirm two declarations.

  The doctor then gets their referral code and QR. `verification_status` starts as `pending` until the team checks
  the registration number.
- Sign-in runs on **Auth0** when `VITE_AUTH0_DOMAIN` and `VITE_AUTH0_CLIENT_ID` are set. Without them it uses
  Supabase's own auth (email + password, Google). The demo build simulates both.

### Set up Auth0 (Google sign-in)
1. Auth0 dashboard → Applications → **Create Application** → *Single Page Application*. Under Settings, add your
   URLs (`http://localhost:5175` and the deployed URL) to *Allowed Callback URLs*, *Allowed Logout URLs* and *Allowed
   Web Origins*. Copy the domain and client ID into `.env`.
2. Authentication → Social → **Google** (`google-oauth2`): enable it for the application. For production, use your
   own Google OAuth client ID and secret; Auth0's development keys are for testing only.
3. Actions → Library → **Create Action** (*Login / Post Login*), then deploy it and add it to the Login flow:
   ```js
   exports.onExecutePostLogin = async (event, api) => {
     api.idToken.setCustomClaim("role", "authenticated");
   };
   ```
   Supabase picks the Postgres role from this claim. It must be on the **ID token**: Auth0 drops un-namespaced claims
   from access tokens.
4. Supabase dashboard → Authentication → **Third-party Auth** → add **Auth0** with your tenant ID (and region if
   the tenant has one).
5. The dashboard sends Auth0's ID token to Supabase on every request. The database identifies people by the token's
   `sub` (`current_sub()` in `schema.sql`), so Auth0 and Supabase-auth users both work. The patient app can use either.

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
| Sign up | Sign in (Auth0 or Supabase auth), then insert its own `patients` row (`auth_sub` fills itself from the token) | nothing yet |
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
