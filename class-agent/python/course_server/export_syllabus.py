"""Export the maintained Markdown through the web syllabus renderer and print styles."""

import argparse
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route, sync_playwright

SYLLABUS_DIRECTORY = Path(__file__).resolve().parents[2] / "shared/course/syllabus"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-url", required=True, help="Running course web frontend URL")
    parser.add_argument("--browser-channel", default="chromium")
    parser.add_argument("--ignore-https-errors", action="store_true")
    args = parser.parse_args()
    source = (SYLLABUS_DIRECTORY / "syllabus.md").read_text(encoding="utf-8")

    def syllabus_source(route: Route) -> None:
        # Export current repository content even if the API has an older catalog loaded.
        if parse_qs(urlparse(route.request.url).query).get("uri") == ["course://syllabus"]:
            route.fulfill(status=200, content_type="text/markdown", body=source)
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.browser_channel)
        try:
            page = browser.new_page(ignore_https_errors=args.ignore_https_errors)
            page.route("**/course/resources/content?*", syllabus_source)
            page.goto(args.web_url)
            page.get_by_role("button", name="About", exact=True).click()
            page.locator(".syllabus-sections table").wait_for()
            page.pdf(
                path=str(SYLLABUS_DIRECTORY / "syllabus.pdf"),
                prefer_css_page_size=True,
                print_background=False,
                tagged=True,
            )
        finally:
            browser.close()
    print("Exported shared/course/syllabus/syllabus.pdf from syllabus.md")


if __name__ == "__main__":
    main()
