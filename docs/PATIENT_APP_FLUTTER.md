# Connecting the Flutter patient app to Auri's sign-in (Auth0) and database (Supabase)

A step-by-step guide for whoever builds the Auri patient app in Flutter. When you finish, a patient can:
- sign in with Google (or email) through **our Auth0 tenant**;
- create their profile and link to their physiotherapist with the `AU-xxxxxx` code;
- read the care plan the physio published;
- save exercise sessions;
- see and join booked video calls.

The physio sees all of it in the clinician dashboard (https://auri-clinician.vercel.app).

The app uses the **same Supabase project and the same Auth0 tenant** as the dashboard. Nothing in Supabase has to
change: the Auth0 link (Supabase Third-Party Auth) and the `role = authenticated` Action already cover every Auth0
application in the tenant.

The source of truth for tables, row-level security and functions is `clinician/supabase/schema.sql`. The contract is
summarised in `clinician/README.md` ("Data contract with the patient app"). Items marked **[unverified]** were not
run on a real phone while writing this guide.

---

## 0. Before you start

### What you get from the Auri team
| Item | Who gives it | Notes |
|---|---|---|
| Auth0 dashboard access (or they create the app for you, step 1) | the project owner | tenant `dev-4cz1sir5jj78abm1.us.auth0.com` |
| Supabase project URL `<SUPABASE_URL>` | the project owner | looks like `https://<project-ref>.supabase.co` |
| Supabase **publishable / anon** key `<SUPABASE_ANON_KEY>` | the project owner | `sb_publishable_…` or the legacy anon JWT |
| A test physio referral code `AU-xxxxxx` | any doctor signed up on the dashboard | shown on the doctor's Profile page |

**Never ask for, store or ship the Supabase secret / service-role key** (`sb_secret_…`). It bypasses row-level
security, and anyone who unpacks the app gets it. The app only ever needs the publishable key.

### What you need on your machine
- Flutter 3.22 or newer (Dart 3.4+). Run `flutter doctor` until it is clean for the platforms you build.
- Android: Android Studio with SDK 34+, and a device or emulator with Google Play services (for Google sign-in).
- iOS (optional): a Mac with Xcode 15+ and CocoaPods; iOS deployment target 13.0+ **[unverified minimum: check
  the auth0_flutter README for the current value]**.
- Decide the app's **package name / bundle ID** now, because it goes into the Auth0 URLs. This guide writes it as
  `<PACKAGE_NAME>` (example `in.auri.patient`). Android `applicationId` and iOS bundle ID should be the same string.

---

## 1. Auth0: a Native application for the phone app

The dashboard uses its own *Single Page Application* in Auth0. The phone app gets a separate **Native** application,
so that it has its own client ID and callback URLs.

1. Auth0 dashboard → **Applications → Applications → Create Application**.
   - Name `Auri Patient`, type **Native** → **Create**.
2. **Settings** tab: copy the **Client ID**. This guide writes it as `<AUTH0_CLIENT_ID>`. It is not secret, but keep
   it out of git anyway (section 7).
3. Choose a custom URL scheme for Android. This guide uses `auri`, written `<SCHEME>`; it must be all lowercase.
4. In **Allowed Callback URLs** *and* **Allowed Logout URLs**, add both lines (comma-separated), then **Save Changes**:
   ```
   auri://dev-4cz1sir5jj78abm1.us.auth0.com/android/<PACKAGE_NAME>/callback,
   <PACKAGE_NAME>://dev-4cz1sir5jj78abm1.us.auth0.com/ios/<PACKAGE_NAME>/callback
   ```
   The format is `SCHEME://DOMAIN/android|ios/PACKAGE/callback`, and every part has to match exactly.
5. Turn on the sign-in methods for this app:
   - **Authentication → Social → google-oauth2 → Applications** tab: switch on `Auri Patient`.
   - **Authentication → Database → Username-Password-Authentication → Applications**: switch on `Auri Patient`
     (only if you want email sign-in).
6. **Do not create another Action.** The tenant already has a post-login Action in the Login flow:
   ```js
   exports.onExecutePostLogin = async (event, api) => {
     api.idToken.setCustomClaim("role", "authenticated");
   };
   ```
   It runs for every application, including this one. Supabase reads `role` from the **ID token** to pick the Postgres
   role, so the app must send the **ID token**, not the access token (section 4).

---

## 2. Platform setup

### Android
`android/app/build.gradle` (or `build.gradle.kts`):
```gradle
android {
    defaultConfig {
        applicationId "<PACKAGE_NAME>"
        minSdkVersion 21          // auth0_flutter needs 21 or higher
        manifestPlaceholders += [auth0Domain: "dev-4cz1sir5jj78abm1.us.auth0.com", auth0Scheme: "auri"]
    }
}
```
Kotlin DSL:
```kotlin
defaultConfig {
    applicationId = "<PACKAGE_NAME>"
    minSdk = 21
    manifestPlaceholders["auth0Domain"] = "dev-4cz1sir5jj78abm1.us.auth0.com"
    manifestPlaceholders["auth0Scheme"] = "auri"
}
```
- auth0_flutter registers the redirect activity from these placeholders, so you do not edit `AndroidManifest.xml`.
- `android/app/src/main/AndroidManifest.xml` must have
  `<uses-permission android:name="android.permission.INTERNET"/>`. Flutter adds it for debug builds only, so check it
  is there for release.

### iOS
- In Xcode → Runner → **Signing & Capabilities**, set the bundle ID to `<PACKAGE_NAME>`.
- On iOS 17.4+, auth0_flutter can use an HTTPS callback or the custom scheme. With the custom scheme (the second
  callback line in step 1.4), the scheme is the bundle ID. Add it to `ios/Runner/Info.plist`:
  ```xml
  <key>CFBundleURLTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeRole</key><string>None</string>
      <key>CFBundleURLName</key><string>auth0</string>
      <key>CFBundleURLSchemes</key>
      <array><string>$(PRODUCT_BUNDLE_IDENTIFIER)</string></array>
    </dict>
  </array>
  ```
  **[unverified on device]**: if login opens and never returns to the app, this entry is the first thing to check.
- `ios/Podfile`: `platform :ios, '13.0'` or higher, then `cd ios && pod install`.

---

## 3. Packages

`pubspec.yaml`:
```yaml
dependencies:
  flutter:
    sdk: flutter
  auth0_flutter: ^1.7.0      # Auth0 sign-in, secure credential storage and refresh
  supabase_flutter: ^2.8.0   # database client; 2.x supports a third-party `accessToken` callback
  url_launcher: ^6.3.0       # opens the Jitsi video room
```
Run `flutter pub get`. These are the versions this guide was written against; newer minor versions should work.
Read their changelogs if something breaks.

---

## 4. Sign-in code: Auth0 signs in, Supabase reads Auth0's ID token

Keys come in at build time with `--dart-define` (section 7), never as literals in git.

`lib/backend.dart`:
```dart
import 'package:auth0_flutter/auth0_flutter.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

const auth0Domain   = 'dev-4cz1sir5jj78abm1.us.auth0.com';
const auth0ClientId = String.fromEnvironment('AUTH0_CLIENT_ID');
const auth0Scheme   = 'auri'; // Android custom scheme from Auth0 step 1.3
const supabaseUrl   = String.fromEnvironment('SUPABASE_URL');
const supabaseKey   = String.fromEnvironment('SUPABASE_ANON_KEY');

final auth0 = Auth0(auth0Domain, auth0ClientId);
SupabaseClient get db => Supabase.instance.client;

/// Call once in main() before runApp.
Future<void> initBackend() async {
  assert(auth0ClientId.isNotEmpty && supabaseUrl.isNotEmpty && supabaseKey.isNotEmpty,
      'Pass --dart-define AUTH0_CLIENT_ID, SUPABASE_URL and SUPABASE_ANON_KEY');
  await Supabase.initialize(
    url: supabaseUrl,
    anonKey: supabaseKey,
    // Every Supabase request carries Auth0's ID token (it has role = authenticated and the user's `sub`).
    // credentials() refreshes the token with the stored refresh token when it has expired.
    accessToken: () async {
      if (!await auth0.credentialsManager.hasValidCredentials()) return null;
      final creds = await auth0.credentialsManager.credentials();
      return creds.idToken;
    },
  );
}

// `offline_access` gives a refresh token, so the patient stays signed in for days, not one hour.
const _scopes = {'openid', 'profile', 'email', 'offline_access'};

Future<Credentials> signInWithGoogle() => auth0
    .webAuthentication(scheme: auth0Scheme)
    .login(parameters: {'connection': 'google-oauth2'}, scopes: _scopes);

Future<Credentials> signInWithEmail() =>
    auth0.webAuthentication(scheme: auth0Scheme).login(scopes: _scopes);

Future<void> signOut() async {
  await auth0.webAuthentication(scheme: auth0Scheme).logout();
  await auth0.credentialsManager.clearCredentials();
}

Future<bool> isSignedIn() => auth0.credentialsManager.hasValidCredentials();
```
- `webAuthentication().login()` saves the credentials in the credentials manager by default, so the `accessToken`
  callback finds them straight after login.
- **Do not** call `Supabase.instance.client.auth.signIn…` or `auth.signOut()`. Sign-in belongs to Auth0, and Supabase
  only reads the token. In this mode, `db.auth.currentUser` stays `null`; that is expected.
- On iOS, `scheme` is ignored when the bundle-ID scheme is used **[unverified]**. Passing it is harmless.

`lib/main.dart`, a minimal auth gate:
```dart
import 'package:flutter/material.dart';
import 'backend.dart';
import 'profile.dart'; // section 5

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initBackend();
  runApp(const MaterialApp(home: AuthGate()));
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});
  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool? _signedIn;
  String? _error;

  @override
  void initState() {
    super.initState();
    isSignedIn().then((v) => setState(() => _signedIn = v));
  }

  Future<void> _login(Future<void> Function() fn) async {
    try {
      await fn();
      setState(() { _signedIn = true; _error = null; });
    } catch (e) {
      setState(() => _error = '$e'); // includes the user closing the browser
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_signedIn == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_signedIn!) {
      return HomeAfterSignIn(onSignOut: () async { await signOut(); setState(() => _signedIn = false); });
    }
    return Scaffold(
      body: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
        FilledButton(onPressed: () => _login(signInWithGoogle), child: const Text('Continue with Google')),
        TextButton(onPressed: () => _login(signInWithEmail), child: const Text('Sign in with email')),
        if (_error != null) Padding(padding: const EdgeInsets.all(16), child: Text(_error!)),
      ])),
    );
  }
}
```

---

## 5. Data: profile, link to physio, care plan, sessions, video calls

Row-level security means a patient only ever reads and writes their **own** rows. The database knows who they are
from the token's `sub` (`current_sub()` in `schema.sql`). The app never sends a user ID for that.

`patients` is the account (`email` from the Auth0 token, `last_seen_at`, `app_version`, plus the latest date of
birth, sex, affected side and conditions). Each submitted intake is a new `patient_intake` row (`version` 1, 2, …).
`patient_consents` records the privacy text (`kind = privacy`) and the share agreement (`kind = share_with_clinician`).
`patient_settings` holds `language` (`en` or `hi`) and `text_size` (`small`, `medium` or `large`). Voice, dark mode
and the reminder time stay on the phone. `patients.intake` is kept for one release and the app no longer writes it.
`session_exercises.reps_rejected` is null when the phone cannot classify the rep. `sessions.ended_early` is true
when the patient stops before the plan is finished.
Run `clinician/supabase/migrations/20261030_patient_app.sql`, then `20261030b_patient_tables.sql`, before these writes succeed.

`lib/profile.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'backend.dart';

/// 1. First sign-in: does this person have a patients row yet? (RLS returns only their own row.)
Future<Map<String, dynamic>?> myPatient() =>
    db.from('patients').select().maybeSingle();

/// 2. Create the profile. auth_sub fills itself from the token (column default current_sub()); don't send it.
Future<Map<String, dynamic>> createPatient({
  required String fullName,
  String? affectedSide,   // 'left' | 'right' | 'both'
  String? sex,            // 'female' | 'male' | 'other' | 'prefer_not_to_say'
  String? dateOfBirth,    // 'YYYY-MM-DD'
  String? phone,
}) =>
    db.from('patients').insert({
      'full_name': fullName,
      if (affectedSide != null) 'affected_side': affectedSide,
      if (sex != null) 'sex': sex,
      if (dateOfBirth != null) 'date_of_birth': dateOfBirth,
      if (phone != null) 'phone': phone,
    }).select().single();

/// 3. Link to the physiotherapist with their code (AU-xxxxxx). The patient agrees to share their data at this
/// moment: show that sentence on screen before calling. Returns the clinician's id.
/// Errors: 'create the patient profile first', 'unknown code', 'not signed in'.
Future<String> linkToPhysio(String code) async =>
    await db.rpc('link_patient_with_code', params: {'p_code': code.trim().toUpperCase()}) as String;

/// Before linking, the patient cannot read the clinicians table. Call this once when they submit a
/// well-formed `AU-` code. An unknown code returns no row. Do not call it on each keystroke.
Future<Map<String, dynamic>?> previewPhysio(String code) async {
  final rows = await db.rpc('preview_clinician_by_code', params: {'code': code.trim().toUpperCase()});
  if (rows is List && rows.isNotEmpty && rows.first is Map) return Map<String, dynamic>.from(rows.first as Map);
  return null;
}

/// The physio(s) I'm linked to, with the video room of each link.
Future<List<Map<String, dynamic>>> myLinks() =>
    db.from('care_links').select('id, status, video_room, clinician_id, clinicians(full_name, clinic, city)')
      .eq('status', 'active');

/// 4. The current care plan with its exercises, in the physio's order.
Future<Map<String, dynamic>?> activePlan() =>
    db.from('care_plans')
      .select('id, version, notes, created_at, plan_items(*, exercises(name, metric, description))')
      .eq('status', 'active')
      .order('position', referencedTable: 'plan_items')
      .maybeSingle();

/// 5. After a session: one sessions row, then one session_exercises row per exercise.
Future<void> saveSession({
  required String patientId,
  String? planId,
  required DateTime startedAt,
  required int durationS,
  int? painBefore, int? painAfter,          // 0-10, patient-reported
  bool? endedEarly,
  required List<Map<String, dynamic>> exercises,
}) async {
  final s = await db.from('sessions').insert({
    'patient_id': patientId,
    'plan_id': planId,
    'started_at': startedAt.toUtc().toIso8601String(),
    'duration_s': durationS,
    'source': 'home',                       // 'home' (phone) | 'station' (clinic station)
    'pain_before': painBefore,
    'pain_after': painAfter,
    'ended_early': endedEarly,              // true if they stopped early; null if unknown
  }).select('id').single();
  await db.from('session_exercises').insert([
    for (final e in exercises) {
      'session_id': s['id'],
      'exercise_id': e['exercise_id'],      // 'flexion' | 'abduction' | 'external_rotation' | ...
      'reps_counted': e['reps_counted'] ?? 0,
      'reps_rejected': e['reps_rejected'],  // null when the phone cannot classify; never a fake 0
      'peak_deg': e['peak_deg'],            // from geometry only; null = unavailable, NEVER 0
      'median_deg': e['median_deg'],
      'flags': e['flags'] ?? <String>[],    // e.g. ['TRUNK_LEAN_SAGITTAL']
    }
  ]);
}

/// 6. Booked or started video calls, newest first. The physio books them in the dashboard.
Future<List<Map<String, dynamic>>> myCalls() =>
    db.from('video_calls').select().inFilter('status', ['scheduled', 'started'])
      .order('scheduled_for', ascending: false);

/// Join: the room belongs to the care link between this patient and that clinician.
Future<void> joinCall(String videoRoom) =>
    launchUrl(Uri.parse('https://meet.jit.si/$videoRoom'), mode: LaunchMode.externalApplication);

/// Screen shown after sign-in: create profile if needed, otherwise show plan/links. Keep it as simple as you like.
class HomeAfterSignIn extends StatelessWidget {
  const HomeAfterSignIn({super.key, required this.onSignOut});
  final VoidCallback onSignOut;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Auri'), actions: [IconButton(onPressed: onSignOut, icon: const Icon(Icons.logout))]),
        body: FutureBuilder(
          future: myPatient(),
          builder: (c, snap) {
            if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
            if (snap.hasError) return Center(child: Text('${snap.error}'));
            if (snap.data == null) return const Center(child: Text('TODO: profile form → createPatient()'));
            return const Center(child: Text('TODO: link code, plan, sessions, calls'));
          },
        ),
      );
}
```

Notes on the data:
- **Exercise ids** come from the `exercises` table (`select id, name from exercises`). Read them; don't hard-code a
  list that can drift.
- **Angles are never 0 for "not measured".** Send `null`. The physio's charts treat 0 as a real measurement.
- **Pain** is 0–10. Each `plan_items` row has a `pain_stop` (default 6), and the app should stop the set at that pain.
- **Targets and progression come from the physio** (`plan_items.rom_target_deg`, `sets`, `reps`, `hold_s`). The app
  displays them and must not change them.
- **The patient cannot change a care plan** or book a call (RLS). Those are read-only for the patient.
- **One patient per Auth0 identity.** Signing in with Google and then with email using the same address gives two
  different `sub`s, and so two patients. Pick one method per person, or link accounts in Auth0.
- **Only active links:** a physio sees a patient only while their `care_links.status` is `'active'`. To end a link,
  update its `status` to `'ended'`, which the patient is allowed to do.

---

## 6. Test it end to end

Checklist:
1. `flutter run --dart-define-from-file=env.json` (section 7). Tap **Continue with Google**, pick an account, and you
   land back in the app.
2. `myPatient()` returns `null` → create the profile → `myPatient()` returns the row.
3. Sign up a test doctor at https://auri-clinician.vercel.app and copy their `AU-` code. Call `linkToPhysio(code)`. In
   the dashboard, that doctor now sees the patient under **Patients**.
4. The doctor publishes a care plan → `activePlan()` returns it with its `plan_items`.
5. `saveSession(...)` → the doctor's patient page shows it under **Progress / Sessions**.
6. The doctor books a video call → `myCalls()` lists it → `joinCall(room)` opens Jitsi, and the doctor joins from the
   dashboard into the same room.
7. Kill the app and reopen: the patient is still signed in (refresh token). Sign out, then reopen: the login screen
   shows.

Common errors:
| Symptom | Cause | Fix |
|---|---|---|
| Auth0 page says "Callback URL mismatch" | the exact URL in step 1.4 is missing; any part differs (scheme, domain, `android`/`ios`, package) | copy the URL from the error into Allowed Callback URLs |
| Login opens, never returns to the app | Android: `auth0Scheme` placeholder ≠ `scheme:` in code. iOS: missing `CFBundleURLTypes` | make all three use the same scheme |
| Supabase `401`, "JWSError", "invalid JWT" | no token sent (signed out / not stored), or Third-Party Auth in Supabase is not set to this tenant | check `hasValidCredentials()`; ask the owner to confirm Supabase → Authentication → Third-party Auth lists Auth0 with this tenant |
| `permission denied for table …` / `role "…" does not exist` | the ID token has no `role = authenticated` claim | the post-login Action is not deployed or not in the Login flow; decode the ID token at jwt.io to see claims |
| Sent the access token instead of the ID token | Auth0 access tokens don't carry the un-namespaced `role` claim | return `creds.idToken`, not `creds.accessToken` |
| Queries return `[]` though the data exists | RLS: the row belongs to someone else, or no `patients` row exists yet for this `sub`, or the link is `ended` | create the profile first; check you're signed in as the right person |
| Insert into `patients` fails with a unique violation | a profile already exists for this sign-in | call `myPatient()` first; insert only when it is `null` |
| `link_patient_with_code` → "unknown code" | typo, or the doctor regenerated their code | codes are `AU-` + 6 characters; get the current one from the doctor's Profile |
| `link_patient_with_code` → "create the patient profile first" | no `patients` row yet | create it, then link |
| Session insert fails a check constraint | `pain_*` outside 0–10, negative `duration_s`, unknown `source`/`exercise_id` | match the values in section 5 |

---

## 7. Keys, builds and release

- **Keep keys out of git.** Create `env.json` (add it to `.gitignore`):
  ```json
  { "AUTH0_CLIENT_ID": "<AUTH0_CLIENT_ID>", "SUPABASE_URL": "<SUPABASE_URL>", "SUPABASE_ANON_KEY": "<SUPABASE_ANON_KEY>" }
  ```
  Run and build with `--dart-define-from-file=env.json`, for example `flutter build apk --release --dart-define-from-file=env.json`.
  The publishable key ends up inside the app, which is fine because RLS protects the data. The secret key must never
  be in the app or in git.
- **Play Store / app signing:** Auth0 web login does not use your SHA-1 or SHA-256 certificate fingerprints. You only
  need those if you later add Android App Links (HTTPS callbacks) or Google's native sign-in SDK, and this guide uses
  neither.
- **Google sign-in in production:** the tenant's Google connection may still use Auth0's development keys, which are
  for testing only. Before a public release, the owner should set the tenant's own Google OAuth client ID and secret
  in Auth0 → Social → Google.
- **Release URLs:** if you change the package name or scheme, update Auth0's Allowed Callback and Logout URLs first.
- **Privacy:** health data. Show the consent sentence before linking to a physio, don't log tokens or API responses
  in release builds, and don't cache health data unencrypted on the device.
