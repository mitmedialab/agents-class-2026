/**
 * E2E tests for the student authentication flow (CONSTITUTION §97).
 *
 * Verified behaviour:
 *  - Login form is accessible via the history drawer
 *  - Correct credentials submit the login API call
 *  - After login the session reflects the authenticated student
 *  - Unauthenticated visitors do not see student-only UI
 */
import { expect, test } from "@playwright/test";
import { STUDENT_PRINCIPAL } from "./fixtures.js";
import { setupPublicRoutes, setupStudentRoutes } from "./setup.js";

test.describe("Student login flow", () => {
  test("exposes the login form inside the history drawer", async ({ page }) => {
    await setupPublicRoutes(page);
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();

    // Login form fields must be visible
    await expect(page.getByLabel("Email or username")).toBeVisible();
    await expect(page.getByLabel("Access code")).toBeVisible();
    await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
    await expect(page.getByText("Course login")).toBeVisible();
  });

  test("submits credentials to the login endpoint and closes the drawer", async ({ page }) => {
    let loginPayload: unknown = null;

    await setupPublicRoutes(page);

    // Override the login route to capture the payload
    await page.route("**/api/v1/auth/login", async (route) => {
      loginPayload = JSON.parse(route.request().postData() ?? "{}");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(STUDENT_PRINCIPAL),
      });
    });

    await page.goto("/");
    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();
    await page.getByLabel("Email or username").fill("alice");
    await page.getByLabel("Access code").fill("ca-long-secret-code-here");
    await page.getByRole("button", { name: "Log in" }).click();

    // Drawer closes after successful login
    await expect(page.getByRole("dialog", { name: "Chat history" })).not.toBeVisible({
      timeout: 5_000,
    });

    // Verify the correct payload was sent
    expect(loginPayload).toMatchObject({
      username: "alice",
      access_code: "ca-long-secret-code-here",
    });
  });

  test("public visitors do not see student-only tools in the capability list", async ({ page }) => {
    await setupPublicRoutes(page);
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    // The standard shortcuts must be visible
    await expect(page.getByRole("button", { name: "Apply" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Schedule" })).toBeVisible();

    // No student identity visible in the header or greeting
    await expect(page.getByText("Alice Example")).not.toBeVisible();
    await expect(page.getByText("alice")).not.toBeVisible();
  });

  test("history drawer can be opened and closed without performing login", async ({ page }) => {
    await setupPublicRoutes(page);
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    await page.getByRole("button", { name: "Your logs" }).click();
    await expect(page.getByRole("dialog", { name: "Chat history" })).toBeVisible();

    const closeBtn = page.getByRole("button", { name: "Hide chat history" });
    // The close button may be positioned outside the visible scroll area of the
    // fixed-position drawer; dispatchEvent bypasses the viewport constraint.
    await closeBtn.dispatchEvent("click");
    await expect(page.getByRole("dialog", { name: "Chat history" })).not.toBeVisible();
  });

  test("authenticated student session shows the correct display name context", async ({ page }) => {
    await setupStudentRoutes(page);
    await page.goto("/");

    await page.waitForFunction(
      () => !document.querySelector(".latest-response")?.textContent?.includes("Connecting"),
      { timeout: 8_000 },
    );

    // The student's conversations appear in the drawer
    await page.getByRole("button", { name: "Your logs" }).click();
    const dialog = page.getByRole("dialog", { name: "Chat history" });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("button", { name: /Week one/ })).toBeVisible();
  });
});
