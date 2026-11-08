"""Documentation, papers, specs and data portals. Facts change rarely, so the checks stay
strict on facts and loose on wording."""

from ..checks import Probe, ToolUsed, Workspace
from ..task import Task, answer

REFERENCE: tuple[Task, ...] = (
    Task(
        "arxiv_trio",
        "reference",
        "https://arxiv.org/",
        "Open the arXiv abstract pages of 1706.03762, 1810.04805 and 2005.14165, each in its "
        "own tab. Download the PDF of every paper into the workspace. Then write summary.md "
        "into the workspace with a table of title, date of the first submitted version (v1) "
        "and number of authors for each paper, and report the same table.",
        checks=(
            ToolUsed("opened tabs", "open_tab", count=2),
            Workspace("3 PDFs downloaded", "**/*.pdf", count=3),
            Workspace(
                "summary written", "**/summary.md", contains=(r"2017", r"2018", r"2020")
            ),
            answer(r"\b8\b", r"\b4\b", r"\b31\b", label="author counts"),
        ),
        max_steps=45,
        tags=("tabs", "download", "files", "write", "extract"),
    ),
    Task(
        "arxiv_pdf",
        "reference",
        "https://arxiv.org/abs/1706.03762",
        "Open the PDF of this paper. Report the BLEU scores of the big Transformer on WMT 2014 "
        "English-German and English-French from the results table, and the training time and "
        "hardware of the big model.",
        checks=(
            answer(r"28\.4", r"41\.[08]", label="BLEU"),
            answer(r"P100", r"3\.5 days|300,?000 steps", label="training"),
        ),
        tags=("pdf", "extract"),
    ),
    Task(
        "owid_csv",
        "reference",
        "https://ourworldindata.org/grapher/population?tab=table&country=~DEU",
        "Download Germany's population data as CSV with the page's download option. Read the "
        "downloaded file and report the population for 2000 and 2020 exactly as written in "
        "the file, and the growth between them in percent with one decimal.",
        checks=(
            Workspace("csv downloaded", "**/*.csv", contains=(r"81797255",)),
            ToolUsed("file read", "read_file"),
            answer(
                r"81[,.\s]?797[,.\s]?255", r"83[,.\s]?628[,.\s]?711", label="values"
            ),
            answer(r"2[.,]2\s?%", label="growth"),
        ),
        max_steps=30,
        # The data set is revised yearly; update the numbers when the UN revision changes.
        tags=("download", "files", "csv", "calculate"),
    ),
    Task(
        "edgar_10k",
        "reference",
        "https://www.sec.gov/edgar/search/",
        "Find Apple Inc.'s annual report on Form 10-K for fiscal year 2023 on EDGAR. Open the "
        "filing document and report total net sales and net income for fiscal 2023, and the "
        "date the report was filed.",
        checks=(
            answer(r"383[,.]?285|383\.3", label="net sales"),
            answer(r"96[,.]?995|97\.0", label="net income"),
            answer(
                r"2023-11-03|november 3,? 2023|3 november 2023|11/0?3/2023",
                label="filing date",
            ),
        ),
        max_steps=40,
        tags=("search", "large-document", "extract"),
    ),
    Task(
        "wcag_new",
        "reference",
        "https://www.w3.org/TR/WCAG22/",
        "List every success criterion that is new in WCAG 2.2 with its number, name and "
        "conformance level. Also name the success criterion that was removed in 2.2.",
        checks=(
            answer(r"2\.4\.11", r"2\.4\.12", r"2\.4\.13", label="focus criteria"),
            answer(r"2\.5\.7", r"2\.5\.8", r"3\.2\.6", label="input and help"),
            answer(r"3\.3\.7", r"3\.3\.8", r"3\.3\.9", label="input assistance"),
            answer(r"4\.1\.1", label="removed"),
        ),
        max_steps=30,
        tags=("large-document", "extract"),
    ),
    Task(
        "mdn_compat",
        "reference",
        "https://developer.mozilla.org/en-US/",
        "Use MDN's search to find Array.prototype.findLast. From its browser compatibility "
        "table report the first desktop versions of Chrome, Firefox and Safari that support "
        "it.",
        checks=(answer(r"\b97\b", r"\b104\b", r"15\.4", label="versions"),),
        max_steps=25,
        tags=("search", "tables", "docs"),
    ),
    Task(
        "pypi_to_github",
        "reference",
        "https://pypi.org/",
        "Search PyPI for the package httpx. Report its latest version, its license and the "
        "Python versions it requires according to PyPI. Then follow the source link to its "
        "repository and report the name of the license file in the repository root.",
        checks=(
            answer(r"0\.\d+\.\d+", r"BSD", label="pypi facts"),
            answer(r">=\s?3\.\d+", label="python requirement"),
            answer(r"LICENSE(\.md)?", label="repository"),
        ),
        max_steps=30,
        tags=("search", "multi-site", "extract"),
    ),
    Task(
        "osm_route",
        "reference",
        "https://www.openstreetmap.org/",
        "Use the directions feature to plan a bicycle route from Brandenburger Tor, Berlin "
        "to Alexanderplatz, Berlin. Report the distance and the duration.",
        checks=(
            Probe("directions open", "location.href", lambda u: "directions" in u),
            answer(r"\b[2-5]([.,]\d+)?\s*km", label="distance"),
            answer(r"\d+\s*(min|minutes|:)", label="duration"),
        ),
        max_steps=30,
        tags=("forms", "autocomplete", "maps"),
    ),
    Task(
        "python_docs",
        "reference",
        "https://docs.python.org/3/",
        "Use the documentation's search to find functools.lru_cache. Report its default "
        "maxsize, in which version the typed parameter was added, and what cache_info() "
        "returns.",
        checks=(answer(r"128", r"3\.3", r"hits", label="facts"),),
        tags=("search", "docs"),
    ),
    Task(
        "wiki_mountains",
        "reference",
        "https://en.wikipedia.org/wiki/K2",
        "Compare K2, Kangchenjunga and Lhotse. Open each article in its own tab. For each "
        "mountain report the elevation in metres, the year of the first ascent and who made "
        "it. Answer with a compact table and the article URLs.",
        checks=(
            ToolUsed("opened tabs", "open_tab", count=2),
            answer(r"8,?611", r"8,?586", r"8,?516", label="elevations"),
            answer(r"1954", r"1955", r"1956", label="first ascents"),
        ),
        tags=("tabs", "extract"),
    ),
    Task(
        "wiki_de_history",
        "reference",
        "https://de.wikipedia.org/wiki/Berliner_Mauer",
        "Finde über die Versionsgeschichte des Artikels heraus, wer die letzte Änderung "
        "gemacht hat, wann sie war und welchen Bearbeitungskommentar sie hatte. Nenne außerdem "
        "aus dem Artikel selbst das Datum des Mauerbaus und des Mauerfalls.",
        checks=(
            Probe(
                "history opened",
                "location.href",
                lambda u: "action=history" in u or "oldid" in u or "diff" in u,
            ),
            answer(r"1961", r"1989", label="dates"),
        ),
        tags=("navigation", "german"),
    ),
)
