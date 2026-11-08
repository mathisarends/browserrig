"""Demo sites built for test automation. Their content is fixed, so the checks are strict
and a failure usually means a broken tool or a model mistake."""

from datetime import date

from browserrig import Secret

from ..checks import Custom, Evidence, NoLeak, Probe, ToolUsed, Workspace
from ..task import Task, answer

# --- Shared credentials. The demo passwords are public; they still go through Secrets so
# every login also tests that the agent types placeholders and never sees the value. ----

SAUCE_PASSWORD = "secret_sauce"
HEROKU_PASSWORD = "SuperSecretPassword!"
QUOTES_PASSWORD = "browserrig-eval-2026"
ORANGE_PASSWORD = "admin123"

PATHNAME = "location.pathname"
UPLOADED = "document.querySelector('#uploaded-files')?.innerText.trim() ?? null"
TODOS = (
    "Object.values(localStorage).map(v => { try { return JSON.parse(v) } "
    "catch { return null } }).find(Array.isArray) ?? null"
)
PAGE_FORM = "JSON.parse(document.body.innerText).form"


def _next_month_15th() -> str:
    today = date.today()
    year, month = (
        (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    )
    return rf"0?{month}/15/{year}"


def _uploaded_was_downloaded(evidence: Evidence) -> str | None:
    uploaded = evidence.probes.get(UPLOADED)
    downloaded = {p.name for p in evidence.workspace.rglob("*.txt")}
    if not uploaded:
        return "nothing uploaded"
    return (
        None
        if uploaded in downloaded
        else f"uploaded {uploaded!r}, downloaded {sorted(downloaded)}"
    )


def _todos_done(todos: list[dict]) -> bool:
    titles = [str(t.get("title", "")).strip() for t in todos]
    return titles == ["Steuer machen", "Benchmark bauen", "PR reviewen"] and not any(
        t.get("completed") for t in todos
    )


PRACTICE: tuple[Task, ...] = (
    Task(
        "saucedemo_checkout",
        "practice",
        "https://www.saucedemo.com/",
        "Log in as standard_user with the password secret. Sort the products by price from "
        "low to high. Add Sauce Labs Onesie, Sauce Labs Bike Light and Sauce Labs Fleece "
        "Jacket to the cart, open the cart and check out as Ada Lovelace, postal code 10115. "
        "On the overview report the item total, the tax and the total, then finish the order "
        "and report the confirmation heading.",
        checks=(
            answer(r"67\.97", label="item total"),
            answer(r"5\.44", r"73\.41", label="tax and total"),
            answer(r"thank you for your order", label="confirmation"),
            Probe(
                "order completed",
                PATHNAME,
                lambda p: p.endswith("checkout-complete.html"),
            ),
            NoLeak("password hidden", SAUCE_PASSWORD),
        ),
        tags=("login", "secrets", "forms", "dropdown", "flow"),
        secrets={
            "SAUCE_PASSWORD": Secret(SAUCE_PASSWORD, domains=("www.saucedemo.com",))
        },
    ),
    Task(
        "saucedemo_infeasible",
        "practice",
        "https://www.saucedemo.com/",
        "Log in as standard_user with the password secret, put the Sauce Labs Bike Light in "
        "the cart and apply the discount code SAVE10 before paying. Do not place the order if "
        "the discount cannot be applied; tell me what happened instead.",
        checks=(
            answer(
                r"(no|not|cannot|can't|couldn't|unable|doesn't|does not|isn't|no way)"
                r"[^.]{0,120}(discount|coupon|promo|code)"
                r"|(discount|coupon|promo|code)[^.]{0,120}"
                r"(no|not|cannot|can't|couldn't|unable|doesn't|does not|isn't)",
                label="reports infeasible",
            ),
            Probe("no order placed", PATHNAME, lambda p: "checkout-complete" not in p),
            NoLeak("password hidden", SAUCE_PASSWORD),
        ),
        max_steps=25,
        tags=("infeasible", "login", "secrets"),
        secrets={
            "SAUCE_PASSWORD": Secret(SAUCE_PASSWORD, domains=("www.saucedemo.com",))
        },
    ),
    Task(
        "heroku_login",
        "practice",
        "https://the-internet.herokuapp.com/login",
        "Log in as tomsmith with the password secret. Report the flash message and the "
        "heading of the secure area, then log out and report the flash message shown after "
        "logging out.",
        checks=(
            answer(r"you logged into a secure area", label="logged in"),
            answer(r"you logged out of the secure area", label="logged out"),
            Probe("back on login page", PATHNAME, lambda p: p.rstrip("/") == "/login"),
            NoLeak("password hidden", HEROKU_PASSWORD),
        ),
        max_steps=20,
        tags=("login", "secrets"),
        secrets={
            "HEROKU_PASSWORD": Secret(
                HEROKU_PASSWORD, domains=("the-internet.herokuapp.com",)
            )
        },
    ),
    Task(
        "heroku_file_roundtrip",
        "practice",
        "https://the-internet.herokuapp.com/download",
        "Download one .txt file from this page and report its first line. Then go to "
        "https://the-internet.herokuapp.com/upload, upload exactly that downloaded file and "
        "report the confirmation.",
        checks=(
            Workspace("txt downloaded", "**/*.txt"),
            ToolUsed("file read", "read_file"),
            ToolUsed("upload tool", "upload_files"),
            Probe("upload confirmed", UPLOADED, bool),
            Custom("uploaded the downloaded file", _uploaded_was_downloaded),
            answer(r"file uploaded", label="answer"),
        ),
        max_steps=30,
        tags=("download", "upload", "files"),
    ),
    Task(
        "heroku_dialogs",
        "practice",
        "https://the-internet.herokuapp.com/",
        "On this site: (1) JavaScript Alerts: dismiss the JS Confirm with Cancel, then answer "
        "the JS Prompt with 'browserrig'; report both result lines. (2) Key Presses: press "
        "Escape and report the result. (3) Nested Frames: report the text of every frame.",
        checks=(
            answer(r"you clicked: cancel", label="confirm dismissed"),
            answer(r"you entered: browserrig", label="prompt answered"),
            answer(r"escape", label="key press"),
            answer(r"left", r"middle", r"right", r"bottom", label="frames"),
        ),
        max_steps=35,
        tags=("dialogs", "keys", "frames"),
    ),
    Task(
        "heroku_pointer",
        "practice",
        "https://the-internet.herokuapp.com/",
        "On this site: (1) Hovers: report the name revealed for each of the three users. "
        "(2) Drag and Drop: drag A onto B and report the header order afterwards in the form "
        "'order: X, Y'. (3) Dynamic Loading example 2: start it and report the text that "
        "appears.",
        checks=(
            answer(r"user1", r"user2", r"user3", label="hovers"),
            answer(r"order:\s*B\W+A", label="drag and drop"),
            answer(r"hello world", label="dynamic loading"),
        ),
        max_steps=35,
        tags=("hover", "drag", "waiting"),
    ),
    Task(
        "heroku_windows_tables",
        "practice",
        "https://the-internet.herokuapp.com/windows",
        "Open the new window from this page and report its heading, then return to the "
        "original window. Next go to https://the-internet.herokuapp.com/tables, sort Example 2 "
        "by Due so the largest amount comes first, and report who owes the most and how much.",
        checks=(
            answer(r"new window", label="new window"),
            answer(r"doe", r"\$?100(\.00)?", label="sorted table"),
        ),
        max_steps=25,
        tags=("tabs", "tables"),
    ),
    Task(
        "w3c_widgets",
        "practice",
        "https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/",
        "Use three W3C ARIA example widgets. (1) On this page type 'New' into the State "
        "combobox and pick the third suggestion; report the value. (2) On "
        "https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/examples/datepicker-dialog/ "
        "open the date picker dialog, choose the 15th of next month and report the date the "
        "text field shows. (3) On "
        "https://www.w3.org/WAI/ARIA/apg/patterns/treeview/examples/treeview-1b/ expand "
        "Projects and then project-5, and list the files inside project-5.",
        checks=(
            answer(r"new mexico", label="combobox"),
            answer(_next_month_15th, label="date picker"),
            answer(r"project-5A", r"project-5F", label="tree view"),
        ),
        max_steps=40,
        tags=("widgets", "combobox", "datepicker", "tree", "keys"),
    ),
    Task(
        "toscrape_books",
        "practice",
        "https://books.toscrape.com/",
        "In the Mystery category, look through every page and find the cheapest book with a "
        "five-star rating. Open its detail page and report its title, price, UPC and how many "
        "copies are available.",
        checks=(
            answer(r"girl you lost", label="right book"),
            answer(r"12\.29", label="price"),
            answer(r"4280ac3eab57aa5d", label="detail page"),
        ),
        max_steps=30,
        tags=("pagination", "filter", "extract"),
    ),
    Task(
        "quotes_austen",
        "practice",
        "https://quotes.toscrape.com/login",
        "Log in with username 'browserrig' and the password secret. Then go through all "
        "pages of quotes and find every quote by Jane Austen. Report how many there are, the "
        "page each is on and its tags. Stay logged in at the end.",
        checks=(
            answer(r"\b5\b|five", label="count"),
            answer(r"aliteracy", r"elizabeth-bennet", r"library", label="tags"),
            Probe(
                "still logged in",
                "!!document.querySelector('a[href=\"/logout\"]')",
                lambda v: v is True,
            ),
            NoLeak("password hidden", QUOTES_PASSWORD),
        ),
        max_steps=40,
        tags=("login", "secrets", "pagination", "extract"),
        secrets={
            "QUOTES_PASSWORD": Secret(
                QUOTES_PASSWORD,
                domains=("quotes.toscrape.com", "http://quotes.toscrape.com"),
            )
        },
    ),
    Task(
        "todomvc_state",
        "practice",
        "https://demo.playwright.dev/todomvc/",
        "Add these todos in order: 'Milch kaufen', 'Steuer machen', 'Benchmark bauen', "
        "'Code reviewen', 'Sport'. Mark 'Milch kaufen' and 'Sport' as completed. Rename "
        "'Code reviewen' to 'PR reviewen' by editing it in place. Then clear the completed "
        "todos and report what is left.",
        checks=(
            Probe("todos stored", TODOS, lambda t: isinstance(t, list) and len(t) > 0),
            Probe("final list", TODOS, _todos_done),
            answer(r"PR reviewen", label="answer"),
        ),
        max_steps=35,
        tags=("forms", "keys", "double-click", "state"),
    ),
    Task(
        "httpbin_form",
        "practice",
        "https://httpbin.org/forms/post",
        "Order a pizza: customer name 'Ada Lovelace', telephone '+44 20 7946 0958', email "
        "'ada@example.org', size Large, toppings Bacon and Onion only, delivery time 19:30, "
        "instructions 'Ring twice'. Submit it and report the 'form' object of the response.",
        checks=(
            Probe(
                "submitted values",
                PAGE_FORM,
                lambda f: (
                    f["custname"] == "Ada Lovelace"
                    and f["size"] == "large"
                    and sorted(
                        f["topping"]
                        if isinstance(f["topping"], list)
                        else [f["topping"]]
                    )
                    == ["bacon", "onion"]
                    and f["delivery"] == "19:30"
                ),
            ),
            answer(r"Ada Lovelace", r"Ring twice", label="answer"),
        ),
        max_steps=25,
        tags=("forms",),
    ),
    Task(
        "orangehrm_employee",
        "practice",
        "https://opensource-demo.orangehrmlive.com/",
        "Log in as Admin with the password secret. In PIM add a new employee with first name "
        "'Ada' and last name 'Browserrig' and save. Then open the PIM Employee List, search for "
        "'Ada Browserrig' and report the Employee Id shown in the results.",
        checks=(
            answer(r"\b\d{3,}\b", label="employee id"),
            Probe(
                "employee listed",
                "document.body.innerText.includes('Browserrig')",
                lambda v: v is True,
            ),
            NoLeak("password hidden", ORANGE_PASSWORD),
        ),
        max_steps=40,
        # Shared public demo that resets now and then; failures may be the site.
        tags=("login", "secrets", "spa", "forms", "shared-demo"),
        secrets={
            "ORANGE_PASSWORD": Secret(
                ORANGE_PASSWORD, domains=("opensource-demo.orangehrmlive.com",)
            )
        },
    ),
)
