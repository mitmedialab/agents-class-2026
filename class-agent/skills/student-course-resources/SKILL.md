---
name: student-course-resources
description: Use course resources restricted to logged-in students, including private class materials and finding classmates or collaborators from applications and project websites.
---

Use only private resource metadata and contents returned by the authorized private-resource tools.
Identity and ownership come from the trusted login context; never ask for or pass a user ID.

List available private resources when the relevant URI is unknown. Read only the resource needed for
the current task, do not reveal internal backing paths, and do not imply that a missing resource exists.
Do not expose private course contents to another user or treat them as public web information.

For requests to find collaborators, teammates, or classmates for the logged-in student:

1. Read the student's own accepted application with `instructor.read_application`, omitting
   `application_id`. Platform code resolves it from the stored account email. Treat this as
   comparison context, never a candidate.
2. List candidates with `instructor.list_applications` and/or `course.list_student_projects`.
   Student listings automatically exclude the requester; there is no matching flag or identity
   argument. Read returned peer records/sites to compare interests and explain the evidence.
3. Recommend only peers from the current listing. Do not reuse the requester or an outdated
   candidate roster from earlier chat. State incomplete coverage when reads fail or a website
   name cannot be resolved. Duplicate first names are omitted from website candidates.

If the account email cannot resolve a personal application or website identity, explain the
specific issue and ask staff to check the existing account/application records. Do not invent
identity links or ask the user to supply an authoritative email or user ID. Students may still
read their own authorized application/site explicitly, but must never be their own candidate.
