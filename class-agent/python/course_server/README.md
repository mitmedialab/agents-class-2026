# Course server package

The course server contains framework-independent authentication, Course Agent orchestration, public resource and private application adapters, PostgreSQL adapters, command-line entry points, and the FastAPI transport. FastAPI remains at the outer adapter boundary and is not imported by `agent_core`.

Package boundaries:

- `course_server.auth` owns access-code, session, principal-resolution, and user-administration behavior.
- `course_server.auth.store.AuthStore` is the application-owned persistence boundary.
- `course_server.agent` owns authorization, public tool/resource definitions, conversation persistence interfaces, and orchestration around `AgentRuntime`.
- `course_server.postgres` implements auth and conversation boundaries with PostgreSQL.
- `course_server.migrations` applies permanent checksummed SQL migrations.
- `course_server.index_resources` generates the public registry from resource sidecars
  and refreshes normalized PostgreSQL course search data.
- `course_server.uploads` owns principal-scoped, expiring chat attachment storage.
- `course_server.admin` is the instructor/admin command line interface.
- `course_server.agent_cli` is the model-backed smoke-test entry point.
- `course_server.api` is the HTTP application factory and production entry point.
