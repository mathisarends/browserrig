"""Demanding tasks on live websites.

Live pages change, so the checks are loose sanity checks, not regression tests. The traces
are the real output: they show where the agent struggles, wastes context or lacks a tool.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    name: str
    url: str
    prompt: str
    # Every pattern must match the final answer (case-insensitive regex).
    expect: tuple[str, ...] = ()
    max_steps: int = 40
    tags: tuple[str, ...] = field(default=())

    def check(self, answer: str) -> list[str]:
        """Patterns the answer misses."""
        return [pattern for pattern in self.expect if not re.search(pattern, answer, re.I | re.S)]


TASKS: tuple[Task, ...] = (
    # --- Wikipedia: long articles, tables, multi-tab research -------------------------------
    Task(
        "wiki_mountains",
        "https://en.wikipedia.org/wiki/K2",
        "Compare K2, Kangchenjunga and Lhotse. Open each article in its own tab. For each "
        "mountain report the elevation in metres, the year of the first ascent and who made "
        "it. Answer with a compact table and the article URLs.",
        expect=(r"8,?611", r"8,?586", r"8,?516", r"1954", r"1955", r"1956"),
        tags=("tabs", "extract"),
    ),
    Task(
        "wiki_tallest_table",
        "https://en.wikipedia.org/wiki/List_of_tallest_buildings",
        "From the main ranking table, list the five tallest completed buildings with height in "
        "metres, city and completion year. Then tell how many of the buildings in that table "
        "are located in Dubai.",
        expect=(r"Burj Khalifa", r"828", r"Merdeka", r"Shanghai Tower", r"632", r"Dubai"),
        tags=("large-table",),
    ),
    Task(
        "wiki_de_history",
        "https://de.wikipedia.org/wiki/Berliner_Mauer",
        "Finde über die Versionsgeschichte des Artikels heraus, wer die letzte Änderung "
        "gemacht hat, wann sie war und welchen Bearbeitungskommentar sie hatte. Nenne außerdem "
        "aus dem Artikel selbst das Datum des Mauerbaus und des Mauerfalls.",
        expect=(r"1961", r"1989"),
        tags=("navigation", "german"),
    ),
    # --- GitHub: SPA navigation, code browsing, issues ---------------------------------------
    Task(
        "github_release",
        "https://github.com/astral-sh/uv",
        "Find the latest release of this repository: its version tag, release date and three "
        "notable changes from the release notes. Also report the repository's license(s) and "
        "approximate star count.",
        expect=(r"\d+\.\d+\.\d+", r"MIT|Apache"),
        tags=("spa",),
    ),
    Task(
        "github_code",
        "https://github.com/pallets/flask",
        "Browse the source code (not the docs) to find the default value of "
        "PERMANENT_SESSION_LIFETIME in Flask's default config, and the file and line where it "
        "is defined. Then find the most recently opened issue that is still open and report its "
        "number and title.",
        expect=(r"31|timedelta", r"app\.py|config"),
        tags=("code", "spa"),
    ),
    Task(
        "github_issue_search",
        "https://github.com/microsoft/vscode/issues",
        "Using the issue search filters, find open issues labeled 'bug' that mention "
        "'terminal' in the title. Report how many there are and the titles and numbers of the "
        "three most recently updated ones.",
        expect=(r"#?\d{5,6}",),
        tags=("search", "spa"),
    ),
    # --- Reddit: infinite feeds, comment trees, consent and login nags ----------------------
    Task(
        "reddit_top",
        "https://www.reddit.com/r/programming/top/?t=week",
        "Find the three highest-voted posts of the past week in r/programming. For the top "
        "one, open its comments and summarise the two most upvoted top-level comments in one "
        "sentence each, with their authors.",
        expect=(r"u/|by |author",),
        tags=("feed", "comments"),
    ),
    Task(
        "reddit_old_search",
        "https://old.reddit.com/r/python/",
        "Search r/python (restricted to that subreddit) for 'uv package manager', sort by top "
        "of all time, and report the three top results with score and comment count. Open the "
        "first one and tell what the post is about.",
        expect=(r"\d+",),
        tags=("search", "forms"),
    ),
    # --- Landing pages: heavy marketing pages, pricing toggles, accordions ------------------
    Task(
        "stripe_pricing",
        "https://stripe.com",
        "Find Stripe's standard pricing for online card payments in the United States "
        "(percentage plus fixed fee) and the extra fee for international cards. Then find "
        "what Stripe Billing costs.",
        expect=(r"2\.9 ?%", r"30 ?¢|\$0\.30|30 cents"),
        tags=("landing",),
    ),
    Task(
        "linear_pricing",
        "https://linear.app",
        "Go to Linear's pricing. Report the plan names with their monthly price per user when "
        "billed yearly and when billed monthly (use the billing toggle if there is one), and "
        "the issue limit of the free plan. Then find in Linear's own documentation or help "
        "center whether non-profits get a discount, and how large it is.",
        expect=(r"Free", r"Business|Basic|Standard", r"(?i)non-?profit"),
        tags=("landing", "toggle", "docs"),
    ),
    Task(
        "notion_pricing",
        "https://www.notion.com",
        "Navigate to Notion's pricing page. Compare the Plus and Business plans: price per "
        "seat (annual billing), and three features Business has that Plus lacks. Find the "
        "answer in the FAQ about what happens to the free plan's block limit for teams.",
        expect=(r"Plus", r"Business"),
        tags=("landing", "accordion"),
    ),
    Task(
        "vercel_docs",
        "https://vercel.com",
        "From Vercel's homepage, find the documentation on Edge Config. Report the maximum "
        "size of an Edge Config store on the Hobby and Pro plans and the read latency Vercel "
        "claims.",
        expect=(r"KB|MB",),
        tags=("landing", "docs"),
    ),
    # --- News and consent walls -------------------------------------------------------------
    Task(
        "spiegel_consent",
        "https://www.spiegel.de",
        "Akzeptiere bzw. schließe den Cookie-Dialog und nenne die drei obersten Schlagzeilen "
        "der Startseite. Öffne die erste und fasse sie in zwei Sätzen zusammen.",
        expect=(r"\w+",),
        tags=("consent-iframe", "german"),
    ),
    Task(
        "hn_thread",
        "https://news.ycombinator.com",
        "Open the comments of the story with the most points currently on the front page. "
        "Report its title, points, comment count and the author of the first top-level "
        "comment, then go to the second page of the front page and report its first story.",
        expect=(r"points?",),
        tags=("pagination",),
    ),
    # --- Forms and widgets ------------------------------------------------------------------
    Task(
        "httpbin_form",
        "https://httpbin.org/forms/post",
        "Order a pizza: customer name 'Ada Lovelace', telephone '+44 20 7946 0958', email "
        "'ada@example.org', size Large, toppings Bacon and Onion only, delivery time 19:30, "
        "instructions 'Ring twice'. Submit it and report the 'form' object of the response.",
        expect=(r"Ada Lovelace", r"large", r"bacon", r"onion", r"19:30", r"Ring twice"),
        tags=("forms",),
    ),
    Task(
        "heroku_gauntlet",
        "https://the-internet.herokuapp.com/",
        "Complete these examples on this site and report each result: "
        "(1) Dynamic Loading example 2: start it and report the text that appears. "
        "(2) JavaScript Alerts: dismiss the JS Confirm, then answer the JS Prompt with "
        "'browserrig'; report both result lines. "
        "(3) Hovers: report the name revealed for each of the three users. "
        "(4) Key Presses: press Escape and report the result. "
        "(5) Nested Frames: report the text of every frame. "
        "(6) Drag and Drop: swap A and B and report the header order afterwards. "
        "(7) File Upload: create a text file named browserrig-upload.txt, upload it and report "
        "the confirmation.",
        expect=(
            r"Hello World",
            r"You clicked: Cancel",
            r"You entered: browserrig",
            r"user1",
            r"user3",
            r"ESCAPE",
            r"MIDDLE",
            r"BOTTOM",
            r"browserrig-upload\.txt",
        ),
        max_steps=70,
        tags=("dialogs", "frames", "hover", "drag", "upload", "keys"),
    ),
    # --- Documents --------------------------------------------------------------------------
    Task(
        "arxiv_pdf",
        "https://arxiv.org/abs/1706.03762",
        "Open the PDF of this paper. Report the BLEU scores of the big Transformer on WMT 2014 "
        "English-German and English-French from the results table, and the training time and "
        "hardware of the big model.",
        expect=(r"28\.4", r"41\.[08]", r"P100"),
        tags=("pdf",),
    ),
    Task(
        "python_docs",
        "https://docs.python.org/3/",
        "Use the documentation's search to find functools.lru_cache. Report its default "
        "maxsize, in which version the typed parameter was added, and what cache_info() "
        "returns.",
        expect=(r"128", r"3\.3", r"hits"),
        tags=("search", "docs"),
    ),
    Task(
        "web_search",
        "about:blank",
        "Search the web: when exactly was Rust 1.0 released, and who announced it on the "
        "official blog? Verify on the official Rust blog.",
        expect=(r"2015", r"May 15|15 May"),
        tags=("search",),
    ),
)


def select(names: str | None) -> list[Task]:
    if not names:
        return list(TASKS)
    wanted = [name.strip() for name in names.split(",") if name.strip()]
    found = {task.name: task for task in TASKS}
    missing = [name for name in wanted if name not in found and not name.startswith("@")]
    if missing:
        raise SystemExit(f"Unknown tasks: {', '.join(missing)}")
    chosen = []
    for name in wanted:
        if name.startswith("@"):
            chosen += [task for task in TASKS if name[1:] in task.tags]
        else:
            chosen.append(found[name])
    return chosen
