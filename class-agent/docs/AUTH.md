# Authentication

Phase 2 implements authentication without an HTTP-framework dependency. `AuthenticationService` and `UserAdminService` depend on the application-owned `AuthStore`; PostgreSQL is one adapter and the in-memory store exists only for deterministic tests.

## Access codes

Access codes are generated from 20 cryptographically random bytes (160 bits) and displayed as grouped Base32 text. PostgreSQL stores only an Argon2id encoded hash using explicit time, memory, parallelism, salt, and output-length parameters. Hash parameters can be upgraded opportunistically after a successful login.

Usernames are normalized to lowercase and restricted to a small portable character set. The login
identifier may be either that username or the account's case-insensitive email address, so course
deployments can present email as the student's login name without changing the stable username
contract. Login failures always return the same invalid-credentials error for an unknown identifier,
inactive user, or incorrect code. A dummy Argon2id hash prevents either unknown-user path from
skipping password work.

The default rate limit permits five failed attempts per known account in fifteen minutes, shared
between its username and email identifiers. Unknown identifiers receive their own normalized
limit. PostgreSQL stores only a hash of the rate-limit key. A successful login clears failures.
The future HTTP layer may add a separate network-origin limit without changing this service.

## Sessions

Authenticated and anonymous sessions use independent 256-bit random bearer tokens. Tokens are domain separated before SHA-256 hashing, and only the hash is stored. Plaintext credentials are returned ephemerally to the caller and redact themselves from `repr` output.

Defaults:

- authenticated sessions: 30 days;
- anonymous sessions/history identity: 7 days;
- no sliding expiration in Phase 2;
- `last_seen_at` updates whenever a principal is resolved.

Logout revokes one authenticated session. Resetting an access code, deactivating a user, or changing a role revokes all existing sessions for that user. Activation never restores revoked sessions.

The Phase 4 FastAPI adapter places opaque tokens in cookies configured with `HttpOnly`, `Secure`, and `SameSite=Lax`. Raw tokens never enter application logs, response bodies, or events. Because `Secure` is unconditional, development clients must use HTTPS to send stored session cookies.

## Principal reconstruction

Authenticated identity, display information, and roles are loaded from the database for every resolved session. Model-controlled IDs are never accepted. Authenticated roles become `public` plus the stored user role. Anonymous sessions produce only the `public` role and use the anonymous session ID as both the anonymous identity and session ID.

Role-scoped course resources are filtered from this trusted principal before their URIs or
tools reach the model. Student resources allow the `student` and `instructor` roles;
instructor resources and private application-review tools allow only `instructor`. TA and
admin do not inherit either audience. Direct content and asset routes apply the same policy
and return `404` for unauthorized resources.

Agent Skill metadata follows the same pre-model boundary. Public skills are visible to every
principal, authenticated skills only after login, student skills to students and instructors,
and instructor skills only to instructors. TA and admin do not inherit student or instructor
skills. Skill and reference tools re-resolve access from the trusted `PrincipalContext`; a
model-provided skill ID or role claim cannot grant access.

When email escalation is configured, `course.ask_ta` is narrower than the normal student-resource
audience: it is exposed only to the exact active `student` role. TA, instructor, admin, and
anonymous principals do not receive it. The recipient address is the stored user email loaded by
platform code; it is never a tool or browser parameter.

The student may hide their name in the staff-facing question. Platform code substitutes an
anonymous label and redacts the account's known name and email from the outgoing question/context,
but this is presentation privacy, not anonymous platform ownership: the stored authenticated user
remains the only reply recipient.
Published FAQ notifications likewise resolve the current active student from the session and never
accept a client-provided user ID.

The API resolves an authenticated cookie first and otherwise resolves or creates an anonymous session. Invalid, revoked, inactive-user, and expired authenticated sessions all become public anonymous requests; the unusable cookie is cleared. Logout revokes the presented authenticated token and clears its cookie.

## Admin CLI

After applying migrations:

```bash
uv run python -m course_server.admin create-user \
  --username alice \
  --name "Alice Example" \
  --email alice@mit.edu \
  --role student

uv run python -m course_server.admin reset-user-code --username alice
uv run python -m course_server.admin deactivate-user --username alice
uv run python -m course_server.admin activate-user --username alice
uv run python -m course_server.admin change-role --username alice --role ta
uv run python -m course_server.admin list-users
```

`DATABASE_URL` must be in the process environment or passed as the global `--database-url` option before the subcommand. Creation and reset print the new code exactly once. The list command returns public user fields only.
