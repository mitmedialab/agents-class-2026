from bs4 import BeautifulSoup

from course_server.peer_discovery.preview import preview_metadata, project_description


def test_project_preview_uses_author_demo_and_valid_heading() -> None:
    page = BeautifulSoup(
        """
        <main><h1>[{"port":443}]</h1><h1>Creative Canvas</h1>
        <h2>References</h2><video poster="lecture.jpg"></video>
        <h2>Demo</h2>
        <figure><img src="diagram.png"><figcaption>Paper reference</figcaption></figure>
        <img src="canvas.png" alt="Canvas interface"><video poster="working.jpg"></video></main>
    """,
        "html.parser",
    )
    root = "https://example.edu/student/week3/"
    assert preview_metadata(page, root) == {
        "cover_url": root + "working.jpg",
        "page_title": "Creative Canvas",
    }
    page.select("video")[-1].decompose()
    assert preview_metadata(page, root)["cover_url"] == root + "canvas.png"
    screenshot = page.select_one("img[alt]")
    assert screenshot is not None
    screenshot.decompose()
    assert preview_metadata(page, root)["cover_url"] == ""


def test_proposal_preview_uses_own_title_slide_and_intro() -> None:
    root = "https://example.edu/portfolio/week7/"
    page = BeautifulSoup(
        """
        <main><h1>River patterns</h1><h2>Slides</h2>
        <img src="other-slide-01.jpg" alt="Slide 1: Other class lecture">
        <img src="slide-01.jpg" alt="Slide 1: River patterns">
        </main>""",
        "html.parser",
    )
    assert preview_metadata(page, root)["cover_url"] == root + "slide-01.jpg"
    heading = page.find("h2")
    assert heading is not None
    heading.string = "Lecture slides"
    assert preview_metadata(page, root)["cover_url"] == ""
    content = (
        "[Home](../)\n\nRiver patterns\n========\n\n"
        "A river sensor that maps changes in flow\nthroughout the day."
    )
    assert project_description(content, "River patterns") == (
        "A river sensor that maps changes in flow throughout the day."
    )
    assert project_description("The agent moves the camera", "Camera tools") == (
        "The agent moves the camera"
    )
