"""Popular sites that change daily. Checks are sanity checks; read the trace."""

from ..task import Task, answer

WILD: tuple[Task, ...] = (
    Task(
        "wiki_tallest_table",
        "wild",
        "https://en.wikipedia.org/wiki/List_of_tallest_buildings",
        "From the main ranking table, list the five tallest completed buildings with height in "
        "metres, city and completion year. Then tell how many of the buildings in that table "
        "are located in Dubai.",
        checks=(
            answer(r"Burj Khalifa", r"828", label="first"),
            answer(r"Merdeka", r"Shanghai Tower", r"632", label="top five"),
            answer(r"Dubai", label="Dubai"),
        ),
        tags=("large-table",),
    ),
    Task(
        "github_release",
        "wild",
        "https://github.com/astral-sh/uv",
        "Find the latest release of this repository: its version tag, release date and three "
        "notable changes from the release notes. Also report the repository's license(s) and "
        "approximate star count.",
        checks=(answer(r"\d+\.\d+\.\d+", r"MIT|Apache"),),
        tags=("spa",),
    ),
    Task(
        "github_code",
        "wild",
        "https://github.com/pallets/flask",
        "Browse the source code (not the docs) to find the default value of "
        "PERMANENT_SESSION_LIFETIME in Flask's default config, and the file and line where it "
        "is defined. Then find the most recently opened issue that is still open and report its "
        "number and title.",
        checks=(answer(r"31|timedelta", r"app\.py|config"),),
        tags=("code", "spa"),
    ),
    Task(
        "github_issue_search",
        "wild",
        "https://github.com/microsoft/vscode/issues",
        "Using the issue search filters, find open issues labeled 'bug' that mention "
        "'terminal' in the title. Report how many there are and the titles and numbers of the "
        "three most recently updated ones.",
        checks=(answer(r"#?\d{5,6}"),),
        tags=("search", "spa"),
    ),
    Task(
        "reddit_top",
        "wild",
        "https://www.reddit.com/r/programming/top/?t=week",
        "Find the three highest-voted posts of the past week in r/programming. For the top "
        "one, open its comments and summarise the two most upvoted top-level comments in one "
        "sentence each, with their authors.",
        checks=(answer(r"u/|by |author"),),
        tags=("feed", "comments"),
    ),
    Task(
        "reddit_old_search",
        "wild",
        "https://old.reddit.com/r/python/",
        "Search r/python (restricted to that subreddit) for 'uv package manager', sort by top "
        "of all time, and report the three top results with score and comment count. Open the "
        "first one and tell what the post is about.",
        checks=(answer(r"\d+"),),
        tags=("search", "forms"),
    ),
    Task(
        "stripe_pricing",
        "wild",
        "https://stripe.com",
        "Find Stripe's standard pricing for online card payments in the United States "
        "(percentage plus fixed fee) and the extra fee for international cards. Then find "
        "what Stripe Billing costs.",
        checks=(answer(r"2\.9 ?%", r"30 ?¢|\$0\.30|30 cents"),),
        tags=("landing",),
    ),
    Task(
        "linear_pricing",
        "wild",
        "https://linear.app",
        "Go to Linear's pricing. Report the plan names with their monthly price per user when "
        "billed yearly and when billed monthly (use the billing toggle if there is one), and "
        "the issue limit of the free plan. Then find in Linear's own documentation or help "
        "center whether non-profits get a discount, and how large it is.",
        checks=(answer(r"Free", r"Business|Basic|Standard", r"non-?profit"),),
        tags=("landing", "toggle", "docs"),
    ),
    Task(
        "notion_pricing",
        "wild",
        "https://www.notion.com",
        "Navigate to Notion's pricing page. Compare the Plus and Business plans: price per "
        "seat (annual billing), and three features Business has that Plus lacks. Find the "
        "answer in the FAQ about what happens to the free plan's block limit for teams.",
        checks=(answer(r"Plus", r"Business"),),
        tags=("landing", "accordion"),
    ),
    Task(
        "vercel_docs",
        "wild",
        "https://vercel.com",
        "From Vercel's homepage, find the documentation on Edge Config. Report the maximum "
        "size of an Edge Config store on the Hobby and Pro plans and the read latency Vercel "
        "claims.",
        checks=(answer(r"KB|MB"),),
        tags=("landing", "docs"),
    ),
    Task(
        "spiegel_consent",
        "wild",
        "https://www.spiegel.de",
        "Akzeptiere bzw. schließe den Cookie-Dialog und nenne die drei obersten Schlagzeilen "
        "der Startseite. Öffne die erste und fasse sie in zwei Sätzen zusammen.",
        checks=(answer(r"\w+"),),
        tags=("consent-iframe", "german"),
    ),
    Task(
        "hn_thread",
        "wild",
        "https://news.ycombinator.com",
        "Open the comments of the story with the most points currently on the front page. "
        "Report its title, points, comment count and the author of the first top-level "
        "comment, then go to the second page of the front page and report its first story.",
        checks=(answer(r"points?"),),
        tags=("pagination",),
    ),
    Task(
        "web_search",
        "wild",
        "about:blank",
        "Search the web: when exactly was Rust 1.0 released, and who announced it on the "
        "official blog? Verify on the official Rust blog.",
        checks=(answer(r"2015", r"May 15|15 May"),),
        tags=("search",),
    ),
)
