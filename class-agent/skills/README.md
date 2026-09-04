# Agent Skills

This directory contains standard Agent Skills. Each skill is a directory with a
`SKILL.md` file and optional `references/` files. The Course Agent scans skill metadata
at startup, discloses only authorized names and descriptions initially, and loads full
instructions or references through explicit tools when relevant.

`registry.json` is not a skill format. It is the platform-owned authorization registry
that maps otherwise standard skill directories to deterministic audiences:

- `public`: anonymous and authenticated principals;
- `authenticated`: every logged-in principal;
- `students`: logged-in students and instructors;
- `instructors`: logged-in instructors only.

Authorization is derived from the trusted `PrincipalContext` before metadata reaches the
model and is checked again when a skill or reference is read.
