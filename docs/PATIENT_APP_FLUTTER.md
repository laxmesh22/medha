# Connecting the Flutter patient app to Auri's database and sign-in

The patient app uses the **same Supabase project and the same Auth0 tenant** as the clinician dashboard. Nothing in
Supabase needs to change: the Auth0 link (Third-Party Auth) and the `role = authenticated` Action already apply to
every Auth0 app in the tenant. The table and RPC contract is in `clinician/README.md` ("Data contract with the
patient app") and `clinician/supabase/schema.sql`.

| Setting | Value |
|---|---|
| Supabase URL | `https://mwucwvcpodluecxqfkva.supabase.co` |
| Supabase key | the **publishable** key (`sb_publishable_…`), never the secret key |
| Auth0 domain | `dev-4cz1sir5jj78abm1.us.auth0.com` |
| Auth0 client ID | from the new **Native** app below (not the dashboard's SPA client ID) |

## 1. Auth0: a second application for the phone app
1. Auth0 → **Applications → Create Application** → name `Auri Patient` → **Native** → Create.
2. In its **Settings**, copy the **Client ID**.
3. Pick the app's package name / bundle ID (example: `in.auri.patient`) and a URL scheme (example: `auri`). Add both
   lines to **Allowed Callback URLs** *and* **Allowed Logout URLs**, then **Save**:
   ```
   auri://dev-4cz1sir5jj78abm1.us.auth0.com/android/in.auri.patient/callback,
   in.auri.patient://dev-4cz1sir5jj78abm1.us.auth0.com/ios/in.auri.patient/callback
   ```
4. **Authentication → Social → google-oauth2 → Applications**: switch on `Auri Patient`.
   **Authentication → Database → Username-Password-Authentication → Applications**: switch on `Auri Patient`.
5. Nothing else: the `Supabase role` post-login Action already runs for this app too.

## 2. Flutter packages
```yaml
dependencies:
  auth0_flutter: ^1.7.0
  supabase_flutter: ^2.8.0
```
Android, `android/app/build.gradle` (`defaultConfig`):
```gradle
manifestPlaceholders += [auth0Domain: "dev-4cz1sir5jj78abm1.us.auth0.com", auth0Scheme: "auri"]
```
iOS needs nothing extra beyond the bundle ID matching the callback URL above.

## 3. Sign in with Auth0, talk to Supabase with Auth0's ID token
```dart
import 'package:auth0_flutter/auth0_flutter.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

final auth0 = Auth0('dev-4cz1sir5jj78abm1.us.auth0.com', '<Auri Patient client ID>');

Future<void> initBackend() async {
  await Supabase.initialize(
    url: 'https://mwucwvcpodluecxqfkva.supabase.co',
    anonKey: '<publishable key>',
    // Supabase checks Auth0's ID token (it carries role = authenticated); auth0_flutter refreshes it.
    accessToken: () async {
      if (!await auth0.credentialsManager.hasValidCredentials()) return null;
      return (await auth0.credentialsManager.credentials()).idToken;
    },
  );
}

Future<void> signInWithGoogle() => auth0
    .webAuthentication(scheme: 'auri')
    .login(parameters: {'connection': 'google-oauth2'}, scopes: {'openid', 'profile', 'email', 'offline_access'});

Future<void> signInWithEmail() => auth0
    .webAuthentication(scheme: 'auri')
    .login(scopes: {'openid', 'profile', 'email', 'offline_access'});

Future<void> signOut() => auth0.webAuthentication(scheme: 'auri').logout();
```
Do **not** call `Supabase.instance.client.auth.signIn…`: sign-in belongs to Auth0; Supabase only reads the token.

## 4. What the patient app does with the data
Row-level security means a patient only ever sees and writes their own rows.

```dart
final db = Supabase.instance.client;

// First sign-in: create the patient profile (auth_sub fills itself from the token).
await db.from('patients').insert({
  'full_name': 'Meera Kulkarni',
  'affected_side': 'right',          // left | right | both
  'sex': 'female',                   // female | male | other | prefer_not_to_say
});

// The patient enters the physiotherapist's referral code (AU-xxxxxx) and agrees to share their data.
final linkId = await db.rpc('link_patient_with_code', params: {'p_code': 'AU-7KQ3MX'});

// The current plan the physio published (exercises, reps, targets, pain stop level).
final plan = await db.from('care_plans').select('*, plan_items(*)').eq('status', 'active').maybeSingle();

// After each exercise session: one sessions row + one session_exercises row per exercise.
final session = await db.from('sessions').insert({
  'patient_id': myPatientId,
  'started_at': DateTime.now().toUtc().toIso8601String(),
  'duration_s': 540,
  'source': 'home',                  // home | station
  'pain_before': 2, 'pain_after': 3, // 0-10, patient-reported
}).select().single();
await db.from('session_exercises').insert({
  'session_id': session['id'],
  'exercise_id': 'flexion',          // flexion | abduction | external_rotation | internal_rotation | pendulum
  'reps_counted': 10, 'reps_rejected': 2,
  'peak_deg': 118.5,                 // from the device geometry only; null = unavailable, never 0
  'flags': ['TRUNK_LEAN_SAGITTAL'],
});

// Booked video calls: open https://meet.jit.si/<care_links.video_room>.
final calls = await db.from('video_calls').select().eq('status', 'scheduled');
```
Check every column name against `clinician/supabase/schema.sql` before shipping; that file is the source of truth.

## 5. Check it works
1. Sign in with Google in the Flutter app, insert the `patients` row, link with a real doctor's `AU-` code.
2. In the dashboard (https://auri-clinician.vercel.app), that doctor sees the patient under **Patients**.
3. Insert a session: the doctor's **Progress** tab shows it.

| Problem | Cause |
|---|---|
| Auth0 "Callback URL mismatch" | the exact callback URL from step 1.3 is missing (scheme, domain, package name all must match) |
| Supabase 401 / "permission denied" | the request had no ID token, or the `Supabase role` Action is not in the post-login flow |
| Insert into `patients` refused | a row for this user already exists (one per sign-in identity) |
| `link_patient_with_code` error | wrong or regenerated code; codes are `AU-` + 6 characters |
