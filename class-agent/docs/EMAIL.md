# Private course-staff email escalation

Email escalation is optional and disabled by default. When enabled, only an authenticated
user whose current stored role is exactly `student` receives `course.ask_ta`. The tool prepares
a private question record and emits a platform-owned confirmation. The confirmation presents the
question's substance and any optional context, not the internal ID, subject, or generated email
wrapper. The tool cannot send mail itself. Only the student's subsequent **Send** action moves the
record into the worker's outbox.

The FastAPI process never contacts the mailbox provider. Run `course_server.mail_worker` as a
separate process.
It sends queued questions to the staff list, polls the configured sender mailbox for replies,
matches replies by `In-Reply-To`/`References` before falling back to the stable question code,
stores the answer privately, emails the student's current account address, and appends
`email.ta_answer.received` to the owned conversation. That staff reply must place `PUBLISH` or
`PRIVATE` on a standalone line immediately before or after the student-facing answer. `PUBLIC` is
accepted as an alias for `PUBLISH`. The worker removes the command and any blank lines between it
and the answer before storing or displaying the student-facing content. `PUBLISH`
also places a student-independent, identity-redacted FAQ candidate in the durable publication outbox.

An instructor may instead resolve a pending question in the Course Agent interface. The editable
confirmation presents a separate **Private**/**Public** visibility choice and records it with the
clean answer in the existing answer, event, notification, and FAQ-publication pipeline. **Private** is the
safe default when no decision was requested. If the original question email was already sent, the
mail worker replies to that staff thread with the online resolution, its decision, and its exact
answer. A question resolved while it is still queued has no external email thread to update.

The worker has a provider-neutral boundary. Set `MAIL_PROVIDER=google_gmail` for Gmail or
`MAIL_PROVIDER=microsoft_graph` for Microsoft 365. A cloned deployment owns its mailbox,
provider credentials, and staff destination; neither provider is a platform-wide assumption.

The notification center projects queued/open student questions as pending communications. For the
student, the stored private answer replaces that pending item and remains unread until acknowledged.
When the responder still resolves to an active staff account, the card also uses that account's
display name to select a matching registered `course://instructors` portrait. The browser receives
only the display name and opaque asset reference, never the responder email or backing path.
For active TA and instructor accounts, queued/open questions appear as staff action items. An
instructor's online reply is routed by an opaque, role-filtered question reference; named questions
show the stored student identity in confirmation while anonymous questions show only an anonymous
label. Notification-center access is role-checked in application code and never accepts a
model-supplied user ID.

## Gmail setup for each deployment

Use a dedicated Gmail or Google Workspace mailbox as the sender/receiver. Do not reuse a personal
mailbox or put OAuth credentials in Git.

1. In a deployment-owned Google Cloud project, enable the Gmail API and configure the OAuth
   consent screen. Use an internal app when the mailbox and operators belong to one Google
   Workspace organization; otherwise configure the mailbox as a test user until the app is ready
   for Google's production verification requirements.
2. Add only `https://www.googleapis.com/auth/gmail.send` and
   `https://www.googleapis.com/auth/gmail.readonly`. Sending needs the first scope. Polling reply
   headers and bodies needs the second; Google classifies `gmail.readonly` as restricted.
3. Create an OAuth client for the operator flow and authorize the dedicated mailbox with offline
   access. Store the resulting client ID, client secret, and refresh token in a mode-`0600`
   `.env.mail` when separating mailbox credentials from the API, or in `.env` for a single-file
   deployment. Never log or commit the refresh token. OAuth apps left in external **Testing**
   status may issue refresh tokens that expire after seven days, so use that mode only for local
   validation.
4. Set the staff recipient to the course forwarding address. This deployment uses
   `cognitive-agents@media.mit.edu`; a cloned course should use its own address.
5. Put every individual staff address that may reply in `MAIL_AUTHORIZED_REPLY_SENDERS`, or create
   an active Class Agent account for that address with role `ta`, `instructor`, or `admin`. Other
   senders, including students, are recorded as rejected and cannot create an answer.

The adapter follows Google's documented [OAuth 2.0 offline-access
flow](https://developers.google.com/identity/protocols/oauth2/web-server), sends RFC 2822 MIME via
[`users.messages.send`](https://developers.google.com/workspace/gmail/api/guides/sending), and
polls with [`users.messages.list`](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).
Review Google's [Gmail scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes)
before moving a deployment beyond local or internal use.

Gmail worker environment:

```dotenv
MAIL_ENABLED=true
MAIL_PROVIDER=google_gmail
MAIL_CLIENT_ID=your-google-oauth-client-id
MAIL_CLIENT_SECRET=your-google-oauth-client-secret
MAIL_REFRESH_TOKEN=your-offline-refresh-token
MAILBOX_ADDRESS=course-agent@your-school.edu
MAIL_STAFF_RECIPIENT_ADDRESS=cognitive-agents@media.mit.edu
MAIL_AUTHORIZED_REPLY_SENDERS=instructor1@your-school.edu,ta1@your-school.edu
MAIL_POLL_INTERVAL_SECONDS=60
```

## Microsoft 365 setup for each deployment

Use a dedicated Microsoft 365 mailbox as the sender/receiver and a separate Entra application
for the worker. Do not reuse a personal mailbox or put credentials in Git.

1. Register a single-tenant application in Microsoft Entra ID and create a client secret.
2. Add Microsoft Graph **application** permissions `Mail.ReadWrite` and `Mail.Send`, then grant
   tenant admin consent. `Mail.ReadWrite` is required because the adapter creates an Outlook
   draft before sending so it can retain the provider and RFC message IDs used for reliable reply
   matching. The worker uses the OAuth client-credentials flow and the
   `https://graph.microsoft.com/.default` scope.
3. Restrict the application to the dedicated mailbox with Exchange Online Application RBAC.
   Unscoped Graph application mail permissions can otherwise reach every mailbox in the tenant.
4. Set the staff recipient to the course's forwarding list. This deployment uses
   `cognitive-agents@media.mit.edu`; a cloned course should use its own list.
5. Put every staff address that may reply in `MAIL_AUTHORIZED_REPLY_SENDERS`, or create an active
   Class Agent account for that address with role `ta`, `instructor`, or `admin`. Other senders,
   including students, are recorded as rejected and cannot create an answer.

Microsoft's current setup references are the
[client-credentials flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow),
[Graph mail permissions](https://learn.microsoft.com/en-us/graph/permissions-reference#mail-permissions),
and [Exchange Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
The adapter creates and sends an Outlook draft so it can retain an
[immutable Graph message ID](https://learn.microsoft.com/en-us/graph/outlook-immutable-id) and
the RFC `Message-ID` used to thread staff replies.

Microsoft 365 worker environment:

Copy `.env.example` to an untracked `.env` and set:

```dotenv
MAIL_ENABLED=true
MAIL_PROVIDER=microsoft_graph
MAIL_TENANT_ID=your-entra-tenant-id
MAIL_CLIENT_ID=your-entra-application-client-id
MAIL_CLIENT_SECRET=your-unquoted-single-line-secret
MAILBOX_ADDRESS=course-agent@your-school.edu
MAIL_STAFF_RECIPIENT_ADDRESS=cognitive-agents@media.mit.edu
MAIL_AUTHORIZED_REPLY_SENDERS=instructor1@your-school.edu,ta1@your-school.edu
MAIL_POLL_INTERVAL_SECONDS=60
```

## Shared environment and operation

`MAILBOX_ADDRESS` is the dedicated provider mailbox that sends questions and receives staff
replies. `MAIL_STAFF_RECIPIENT_ADDRESS` is the forwarding list that receives new questions.
These may be different addresses. Mailbox secrets are never placed in events, tool arguments,
logs, or browser responses.

The systemd worker loads the deployment's mode-`0600` `.env` first, then an optional mode-`0600`
`.env.mail`. Keep shared settings such as `DATABASE_URL`, `MAIL_ENABLED`, and storage paths in
`.env`. For production process separation, put the complete provider credential block in
`.env.mail`; values there override the shared file and keep mailbox credentials out of the
request-serving process. A single-file deployment may instead keep that block in `.env`.

Apply migrations and restart the API so student capability filtering sees mail as enabled:

```bash
uv run python -m course_server.migrations apply
uv run python -m course_server.mail_worker --once
uv run python -m course_server.mail_worker
```

`--once` processes the mail currently available and then exits; the API does not poll the mailbox.
During local end-to-end testing, keep the second command running if later replies should be picked
up automatically. Once a worker cycle publishes an answer, FAQ reads and search see the updated
local JSON immediately and the API does not need to restart.

Production should install both `deploy/class-agent-api.service` and
`deploy/class-agent-mail-worker.service`; the worker unit reads the shared protected `.env` and
then an optional protected `.env.mail` override. Create `var/course-knowledge/` before starting the
hardened worker; its unit grants that directory the narrow write access required for atomic FAQ
publication. Only one mail worker should run for a mailbox. The worker overlaps polling windows and
deduplicates provider message IDs so an ordinary retry does not create a second answer.

## Accounts and login

Every student account already requires an email address. Students may enter that address or the
portable stored username in the login field; the access code remains the second credential. Mail
address, user ID, role, and conversation ownership are always reloaded from server-side state.
The agent and browser cannot select a recipient or impersonate another student.

For a cloned course, create users normally and supply their real delivery address:

```bash
uv run python -m course_server.admin create-user \
  --username student-alias \
  --name "Student Name" \
  --email student@your-school.edu \
  --role student
```

The student can log in as `student@your-school.edu`; the internal username remains a small,
portable identifier and does not need to contain `@`.

## Email answer and FAQ decision

The original course-staff email contains the complete moderation instructions. Put the decision
on its own line immediately before or after the answer:

```text
PUBLISH
Assignments 2 and 4 are completed in groups.
```

or:

```text
PRIVATE
This exception applies only to the student who asked.
```

The command may instead follow the answer:

```text
Assignments 2 and 4 are completed in groups.
PUBLISH
```

Both decisions send the answer privately to the student. `PUBLISH` additionally approves the
redacted original question and answer as shared course knowledge; `PRIVATE` does not. Only
configured reply senders or active `ta`, `instructor`, and `admin` accounts can decide. Missing,
conflicting, or mid-answer commands are recorded and leave the question open for a corrected
reply. A published entry
is stored in PostgreSQL, appears immediately in `course://faq` reads and search, and creates an
unread course notification for each student account. Publishing is idempotent per source question.
The worker also atomically adds the public question and answer to the local JSON file configured by
`PUBLISHED_FAQ_PATH`; the Course Agent reads that file through `course://faq`. No private email
workflow fields are written to it.

The online instructor confirmation uses the same two decisions through a separate visibility
control, while the answer remains command-free. Only the answer content is shown to the student. Online
answers replace the pending question in the student's Communications stack; they are not also
projected as a duplicate direct instructor message.

Students can select **Hide my name from course staff** before sending. The platform still retains
the authenticated owner so it can route the private answer; the outgoing staff message substitutes
an anonymous label and redacts the account's known name and email from the question and included
context. The model cannot autonomously send an anonymous report.

## Optional instructor message copies

For ordinary instructor messages to all or selected students, the Send/Cancel preview includes
**Also send by email**, unchecked by default. It is disabled when `MAIL_ENABLED` is false.
The instructor confirms this choice together with the exact edited subject and body. The tool
cannot select email delivery. In-app delivery always occurs; question replies retain their existing
visibility and staff-thread workflow.

The confirmed `send_email` flag and fixed recipient rows form a durable outbox, committed in the
same conditional update as the reviewed content. The existing `course_server.mail_worker` sends
one plain-text email per recipient using the configured mailbox and their current active student
account address. Other recipients' addresses are never included. New students added after draft
preparation are excluded. Inactive accounts or accounts that no longer have the student role are
skipped; they remain pending and can be delivered if restored to active student status.

Each recipient records attempts, a sanitized error class, and the provider ID and timestamp on
success. Failures retry on subsequent worker cycles without repeating successful recipients;
row locks prevent concurrent cycles from sending the same recipient simultaneously. Provider
acceptance followed by a crash before recording success can still result in a duplicate on retry.
These adapters do not provide a shared exactly-once delivery guarantee. Queue acceptance is
reported separately from email delivery; there is no instructor delivery-status UI in this change.

Apply migration `0014_instructor_message_email` and restart the API and mail worker. Existing
messages default to in-app only and are not emailed retroactively. No additional credentials or
provider permissions beyond the existing configured mail adapter are required.
