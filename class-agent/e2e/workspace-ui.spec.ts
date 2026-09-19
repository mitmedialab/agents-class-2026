/**
 * E2E tests for the dynamic workspace UI (CONSTITUTION §99).
 *
 * Verified behaviour:
 *  - Schedule shortcut opens the Calendar workspace panel
 *  - The workspace panel can be closed by the user
 *  - The compositor disables while an agent run is in progress
 *  - Sending a plain message streams text and updates the response area
 *  - MIT logo resets to a fresh conversation and clears the composer
 */
import { expect, test } from "@playwright/test";
import { AGENT_MESSAGE_EVENT, CONVERSATION, calendarSseStream, textSseStream } from "./fixtures.js";
import { setupPublicRoutes } from "./setup.js";

async function openExistingConversation(page: import("@playwright/test").Page): Promise<void> {
  await page.waitForFunction(
    () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
    { timeout: 8_000 },
  );
  await page.getByRole("button", { name: "Your logs" }).click();
  await page.getByRole("button", { name: /Week one/ }).click();
  await page.locator(".latest-response").waitFor({ state: "visible", timeout: 5_000 });
}

test.describe("Workspace and dynamic UI", () => {
  test("Schedule shortcut opens a calendar workspace panel", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });

    // Override the stream route to return a workspace command
    await page.route("**/api/v1/conversations/*/run/stream", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
        },
        body: calendarSseStream("Here is the course schedule."),
      }),
    );

    // Schedule resource content
    await page.route("**/api/v1/course/resources/content**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "provisional",
          events: [
            {
              id: "review",
              title: "Project review",
              start: "2026-10-08T11:00:00-04:00",
              type: "class",
            },
          ],
        }),
      }),
    );

    await page.goto("/");
    await openExistingConversation(page);

    await page.getByRole("button", { name: "Schedule" }).click();

    // Workspace panel must appear
    const workspace = page.getByRole("complementary", { name: "Workspace" });
    await expect(workspace).toBeVisible({ timeout: 5_000 });

    // Agent response text streams in
    await expect(page.locator(".latest-response")).toContainText("Here is the course schedule.", {
      timeout: 5_000,
    });

    // Standard shortcut buttons are hidden while the workspace is open
    await expect(page.getByRole("button", { name: "Apply" })).not.toBeVisible();
  });

  test("user can close the workspace panel and return to the conversation", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });

    await page.route("**/api/v1/conversations/*/run/stream", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
        },
        body: calendarSseStream("Schedule is shown."),
      }),
    );

    await page.route("**/api/v1/course/resources/content**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "provisional", events: [] }),
      }),
    );

    await page.route("**/api/v1/conversations/**/workspace/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...AGENT_MESSAGE_EVENT,
          type: "workspace.panel.closed",
          payload: { command: { type: "close", panel_id: "40000000-0000-4000-8000-000000000001" } },
        }),
      }),
    );

    await page.goto("/");
    await openExistingConversation(page);

    await page.getByRole("button", { name: "Schedule" }).click();

    const workspace = page.getByRole("complementary", { name: "Workspace" });
    await expect(workspace).toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: "Close workspace" }).click();

    await expect(workspace).not.toBeVisible({ timeout: 5_000 });

    // Shortcut buttons reappear after workspace closes
    await expect(page.getByRole("button", { name: "Apply" })).toBeVisible();
  });

  test("message composer is disabled while an agent run is in progress", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });

    // Use a never-resolving promise to simulate an in-flight agent run
    await page.route("**/api/v1/conversations/*/run/stream", (route) => {
      // Intentionally do not call route.fulfill() — the request stays pending
      // which keeps the composer in its disabled state
      void route;
    });

    await page.goto("/");
    await openExistingConversation(page);

    const composer = page.getByRole("textbox", { name: "Message" });
    await composer.fill("What is due next?");
    await composer.press("Enter");

    await expect(composer).toBeDisabled({ timeout: 3_000 });
  });

  test("sends a typed message and shows the streamed agent reply", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });

    await page.route("**/api/v1/conversations/*/run/stream", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        },
        body: textSseStream("The final project is due in week twelve."),
      }),
    );

    await page.goto("/");
    await openExistingConversation(page);

    const composer = page.getByRole("textbox", { name: "Message" });
    await composer.fill("When is the final project due?");
    await composer.press("Enter");

    await expect(page.locator(".latest-response")).toContainText(
      "The final project is due in week twelve.",
      { timeout: 5_000 },
    );
    await expect(composer).toBeEnabled({ timeout: 3_000 });
  });

  test("MIT logo click starts a fresh conversation and clears the composer", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });

    await page.goto("/");
    // Wait until past the splash
    await expect(page.getByTestId("opening-splash")).not.toBeVisible({ timeout: 6_000 });

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    const composer = page.getByRole("textbox", { name: "Message" });
    await composer.fill("An unsent draft message");
    await page.getByRole("button", { name: "MIT", exact: true }).click();

    // Composer should be cleared and the welcome message restored
    await expect(composer).toHaveValue("");
    await expect(page.locator(".latest-response")).toContainText("Welcome", { timeout: 5_000 });
  });
});
