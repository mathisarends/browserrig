# Live-site benchmark

Missions on real websites that show whether the agent's tools work and where it
struggles. Each task has several milestones (checks), so a long mission shows how far
the agent got, not only whether it passed.

## Run

```sh
evals/bench.sh smoke                 # 5 quick practice tasks, one per core capability
evals/bench.sh practice              # all practice tasks
evals/bench.sh reference --repeat 2  # research tasks, twice each
evals/bench.sh wild                  # popular sites, realism check
evals/bench.sh saucedemo_checkout --headed
evals/bench.sh @upload,@download     # every task with these tags
evals/bench.sh list                  # what exists
```

The script needs `uv` and `OPENAI_API_KEY` in `.env`. On Windows run it from Git Bash.
At the end it prints a summary and compares scores with the latest earlier run that
shares tasks. Results land in `evals/results/<timestamp>-<label>.json`; each run's
downloads and written files stay in `evals/results/workspaces/`.

```sh
evals/bench.sh report evals/results/<run>.json --against evals/results/<older>.json
```

## Stages

| Stage | Sites | Checks | Run it |
|---|---|---|---|
| `practice` | the-internet, saucedemo, httpbin, W3C ARIA examples, toscrape, TodoMVC, OrangeHRM | strict, content is fixed | after changes to tools or prompts |
| `reference` | arXiv, Our World in Data, SEC EDGAR, W3C specs, MDN, PyPI, OpenStreetMap, Wikipedia, Python docs | strict on facts | weekly, before releases |
| `wild` | GitHub, Reddit, HN, pricing pages, news | sanity only, read the trace | weekly, before releases |

A failure in `practice` usually means a broken tool or a model mistake. In `reference`
and `wild` check the site first. `orangehrm_employee` uses a shared public demo that
resets now and then.

## Reading results

- `pass` means the run finished and reached every milestone. `fail` lists the
  missed milestones. `error` means the harness or site crashed, not the agent.
- **Capabilities, weakest first** averages scores per tag, such as `upload`,
  `login` or `widgets`. This is where broken tools show up.
- Run with `--repeat 3` before trusting a single regression; live sites are noisy.
- With `--trace`, start Phoenix first (`docker compose up -d --wait`). Then
  `uv run python -m evals.analyze evals/results/<run>.json` shows how the
  context grows per step.

## Checks

Defined in `evals/checks.py` and attached per task in `evals/suites/`:

| Check | Milestone |
|---|---|
| `Answer` | The final answer matches regexes; a pattern may be computed, such as next month's date |
| `Workspace` | Files matching a glob exist in the workspace, optionally containing text |
| `ToolUsed` | A tool such as `upload_files` or `open_tab` succeeded at least n times |
| `Probe` | JavaScript on the active tab, read before the browser closes, such as localStorage or the URL |
| `NoLeak` | A secret never reaches the answer, the tool arguments or the model history |
| `Custom` | Any other condition on the evidence |

Logins use `Secrets`, so every login also tests that the agent types
`{{secret:NAME}}` and never sees the password. The demo passwords are public.

## Add a task

Add a `Task` to the stage module in `evals/suites/`. Use a unique name, a start URL,
a prompt and at least one check. Tag the capabilities it exercises. Verify the
expected values against the live site before relying on them.
