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


def test_preview_rejects_architecture_and_results_charts() -> None:
    root = "https://example.edu/week05/"
    page = BeautifulSoup(
        """
    <main><h1>Reappraisal game</h1>
    <h2>Interface</h2><img src="yourturn.png" alt="Your turn screen">
    <h2>Results</h2><img src="emotion.png" alt="Feeling over three sessions">
    <h2>Demo</h2><img src="architecture-diagram.png" alt="System architecture">
    </main>""",
        "html.parser",
    )
    assert preview_metadata(page, root)["cover_url"] == root + "yourturn.png"


def test_preview_can_find_an_unlabelled_room_screenshot() -> None:
    page = BeautifulSoup(
        '<h1>The Library</h1><h2>Design framework</h2><img src="theory.png">'
        '<h2>The room</h2><img src="a2f.png">',
        "html.parser",
    )
    assert (
        preview_metadata(page, "https://example.edu/week3/")["cover_url"]
        == "https://example.edu/week3/a2f.png"
    )


def test_borrowing_excerpts_reject_table_rows_and_ai_disclosures() -> None:
    from course_server.peer_discovery.preview import evidence_passages

    sentence = (
        "The interface keeps the previous branch visible while the student compares alternatives."
    )
    source = (
        "| Diversity | Rated relevant | Runs passed | pass@3 |.\n"
        "I used Claude Code and Codex as my coding assistants for this project.\n" + sentence
    )
    assert evidence_passages(source) == [sentence]


def test_homepage_curated_poster_wins_over_decorative_disc() -> None:
    from course_server.peer_discovery.preview import portfolio_covers

    page = BeautifulSoup(
        """
    <a href="week02/"><img src="assets/disc-garden.png"></a>
    <a href="week02/"><video poster="assets/week02/demo-cover.jpg"></video></a>
    <a href="week03/"><img src="assets/week03/canvas.png"></a>
    <a href="week04/"><img src="https://other.example/logo.jpg"></a>
    """,
        "html.parser",
    )
    assert portfolio_covers(page, "https://example.edu/raine/") == {
        "https://example.edu/raine/week02/": "https://example.edu/raine/assets/week02/demo-cover.jpg",
        "https://example.edu/raine/week03/": "https://example.edu/raine/assets/week03/canvas.png",
    }
