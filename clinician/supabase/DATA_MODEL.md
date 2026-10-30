# Patient data model

The patient app and the clinician dashboard share one Supabase project. `patients` stays the account row, because care links, plans, sessions and video calls already point at it. What the app collects on top of that profile lives in its own tables so it is obvious what was gathered, and when.

Run `migrations/20261030_patient_app.sql` first, then `migrations/20261030b_patient_tables.sql`.

## Tables

### `patients` — the account

Kept. One row per signed-in person (`auth_sub` from the token).

| Column | Source | Why |
|---|---|---|
| `auth_sub` | Auth0 `sub` | Who this row belongs to. Not typed. |
| `full_name` | Auth0 name, then the patient can edit it | What the physio sees |
| `email` | `auth.jwt()->>'email'` | Shown on the profile. Not typed in the app |
| `last_seen_at` | App, on each load | Whether the account is still in use |
| `app_version` | App (`0.1.0`) | Which build wrote the row |
| `date_of_birth`, `sex`, `affected_side`, `conditions` | Latest submitted intake | Snapshot the dashboard already uses for age, side and conditions |
| `phone`, `dominant_side`, `diagnosis`, `symptom_onset`, `medications`, `notes` | Clinician, not the app | Clinical record |
| `intake` jsonb | Old builds only | Kept for one release after the copy into `patient_intake`. The current app does not write it |

### `patient_intake` — one row per submitted intake

History is kept. A new submit inserts the next `version`. Nothing here is updated in place.

Typed columns: `date_of_birth`, `sex`, `gender`, `affected_side`, `onset`, `trigger`, `trigger_note`, `main_problem`, `pain_now`, `sleep`, `hard_tasks`, `load`, `load_increased`, `load_note`, `past_injury`, `past_injury_when`, `prior_frozen`, `conditions`, `seen_before`, `seen_who`.

`extra` jsonb is only for a question the app does not have a column for yet. The known questions above are not stored in `extra`.

The latest row is also copied onto the snapshot columns of `patients` so the existing dashboard lists keep working.

### `patient_consents`

| `kind` | When |
|---|---|
| `privacy` | The patient agrees on the sign-in screen. `version` is the text version (`2026-10-draft`) |
| `share_with_clinician` | The patient confirms a physio's code. `clinician_id` is who they agreed to share with |

Existing care links are copied in as `share_with_clinician` with version `recorded-at-link` and the link's `consent_at`. That is the time we actually have. It is not a guess at the privacy text.

### `patient_settings`

One row per patient. `language` and `text_size` only. The physio can read them. The patient writes them.

## Who can see a row

The patient reads and writes only their own rows. A linked clinician reads intake, consents and settings, and does not write them. No one else has a policy. Intake and consents are insert-only, so a later submit does not erase the earlier one.

Deleting a patient cascades to intake, consents and settings.

## What stays on the phone

| Data | Why it is not in the database |
|---|---|
| Voice-guidance on/off, dark mode | Display preferences. Nothing clinical reads them |
| Reminder time | The phone's own notification alarm |
| Raw microphone audio | The privacy text says it is not kept. Only the answers are stored |
| Per-set pain scores | The session stores the first and last score as `pain_before` and `pain_after`. The dashboard does not use the scores in between |
| A separate pain-check or event log | Nothing reads one, so it is not created |

Session rows (`sessions`, `session_exercises`) stay as they are: the exercise record, including `ended_early` and `reps_rejected` (null when the phone could not classify).
