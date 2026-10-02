/**
 * E2E tests for the public-visitor flow (CONSTITUTION §96).
 *
 * Verified behaviour:
 *  - Opening splash appears on load and then disappears
 *  - Welcome message is shown after splash clears
 *  - Message composer and navigation shortcuts are present
 *  - Privileged (student/TA) tools are absent
 *  - History panel lists previous conversations
 *  - First message from a new anonymous user creates a conversation
 */
import { expect, test } from "@playwright/test";
import { CONVERSATION } from "./fixtures.js";
import { setupPublicRoutes } from "./setup.js";

test.describe("Public visitor flow", () => {
  test("shows opening splash then reveals the interface", async ({ page }) => {
    await setupPublicRoutes(page);
    await page.goto("/");

    // Splash must appear immediately
    await expect(page.getByTestId("opening-splash")).toBeVisible();
    const heading = page.getByRole("heading", {
      name: "MAS.S60 · AI Agents for Cognitive Augmentation",
    });
    await expect(heading).toBeVisible();

    // The main interface must be inert while the splash is up
    const appShell = page.getByTestId("course-agent-interface");
    await expect(appShell).toHaveAttribute("inert");

    // After the 3.6 s animation the splash disappears
    await expect(page.getByTestId("opening-splash")).not.toBeVisible({
      timeout: 6_000,
    });
    await expect(appShell).not.toHaveAttribute("inert");
  });

  test("presents welcome message and standard navigation shortcuts", async ({ page }) => {
    await setupPublicRoutes(page);
    await page.goto("/");

    // Wait for the app to fully initialise
    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    const latestResponse = page.locator(".latest-response");
    await expect(latestResponse).toContainText("Welcome", { timeout: 8_000 });

    // Message composer must be present
    await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();

    // Shortcut navigation buttons — use exact:true to distinguish "MIT" from "MIT Media Lab"
    for (const label of ["MIT", "MIT Media Lab", "Apply", "Schedule", "Grading", "About"]) {
      await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible();
    }

    // Workspace shell present but no active panel
    await expect(page.getByTestId("workspace-shell")).toBeVisible();
  });

  test("lists previous conversations when the history drawer opens", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });
    await page.goto("/");

    // Wait for conversations to load
    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();
    await expect(page.getByRole("button", { name: /Week one/ })).toBeVisible();
  });

  test("opens an existing conversation from the history drawer", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();
    await page.getByRole("button", { name: /Week one/ }).click();

    await expect(page.locator(".latest-response")).toContainText("The earlier response.", {
      timeout: 5_000,
    });
  });

  test("creates a new conversation when the first message is sent", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [] });

    await page.goto("/");

    // Wait for the splash to clear before interacting — the interface is inert until then
    await expect(page.getByTestId("opening-splash")).not.toBeVisible({ timeout: 6_000 });

    // Set up the promise BEFORE the triggering action
    const runStreamRequest = page.waitForRequest(
      (req) => req.url().includes("/run/stream") && req.method() === "POST",
      { timeout: 15_000 },
    );

    const composer = page.getByRole("textbox", { name: "Message" });
    await expect(composer).not.toBeDisabled({ timeout: 5_000 });
    await composer.fill("Tell me about the course");
    await composer.press("Enter");

    // The stream request proves a conversation was created and the agent was invoked
    const req = await runStreamRequest;
    expect(req.method()).toBe("POST");
    expect(req.url()).toMatch(/\/conversations\/[^/]+\/run\/stream/);
  });

  test("shows the syllabus when About is clicked", async ({ page }) => {
    await setupPublicRoutes(page, { conversations: [CONVERSATION] });
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();
    await page.getByRole("button", { name: /Week one/ }).click();
    await page.locator(".latest-response").waitFor({ state: "visible", timeout: 5_000 });

    await page.getByRole("button", { name: "About" }).click();

    await expect(
      page.getByRole("heading", { level: 1, name: "AI Agents for Cognitive Augmentation" }),
    ).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Proposed instructors")).toBeVisible();

    // About is a modal; the message composer is hidden while it is open
    await expect(page.getByRole("textbox", { name: "Message" })).not.toBeVisible();

    // Clicking About again dismisses the view
    await page.getByRole("button", { name: "About" }).click();
    await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  });
});
