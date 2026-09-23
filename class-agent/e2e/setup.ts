/**
 * Route-interception helpers that mock the FastAPI backend for E2E tests.
 * Call these before navigating to the page so all API calls are handled.
 */
import type { Page } from "@playwright/test";
import {
  AGENT_MESSAGE_EVENT,
  CONVERSATION,
  PUBLIC_PRINCIPAL,
  SCHEDULE_JSON,
  STUDENT_PRINCIPAL,
  SYLLABUS_MARKDOWN,
  textSseStream,
} from "./fixtures.js";

/** Wire up the minimal routes every test needs (public session, empty history). */
export async function setupPublicRoutes(
  page: Page,
  options: {
    conversations?: object[];
    notifications?: object[];
  } = {},
): Promise<void> {
  const { conversations = [], notifications = [] } = options;

  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PUBLIC_PRINCIPAL),
    }),
  );

  await page.route("**/api/v1/conversations", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(conversations),
      });
    }
    // POST – create conversation
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CONVERSATION),
    });
  });

  await page.route("**/api/v1/notifications", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(notifications),
    }),
  );

  await page.route("**/api/v1/notifications/**", (route) =>
    route.fulfill({ status: 204, body: "" }),
  );

  await setupResourceRoutes(page);
  await setupConversationRoutes(page);
}

/** Wire up student-authenticated session routes. */
export async function setupStudentRoutes(page: Page): Promise<void> {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(STUDENT_PRINCIPAL),
    }),
  );

  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(STUDENT_PRINCIPAL),
    }),
  );

  await page.route("**/api/v1/auth/logout", (route) =>
    route.fulfill({ status: 204, body: "" }),
  );

  await page.route("**/api/v1/conversations", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([CONVERSATION]),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CONVERSATION),
    });
  });

  await page.route("**/api/v1/notifications", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    }),
  );

  await setupResourceRoutes(page);
  await setupConversationRoutes(page);
}

async function setupResourceRoutes(page: Page): Promise<void> {
  await page.route("**/api/v1/course/resources/content**", (route) => {
    const url = route.request().url();
    if (url.includes("course%3A%2F%2Fsyllabus") || url.includes("course://syllabus")) {
      return route.fulfill({
        status: 200,
        contentType: "text/markdown",
        body: SYLLABUS_MARKDOWN,
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: SCHEDULE_JSON,
    });
  });
}

async function setupConversationRoutes(page: Page): Promise<void> {
  await page.route("**/api/v1/conversations/*/run/stream", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
      body: textSseStream("I can help you with that."),
    }),
  );

  await page.route("**/api/v1/conversations/20000000*", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          conversation: CONVERSATION,
          events: [AGENT_MESSAGE_EVENT],
        }),
      });
    }
    return route.fulfill({ status: 204, body: "" });
  });

  await page.route("**/api/v1/conversations/**/workspace/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(AGENT_MESSAGE_EVENT),
    }),
  );
}
