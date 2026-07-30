# Fork-specific notes

This is a fork of [TideDra/zotero-arxiv-daily](https://github.com/TideDra/zotero-arxiv-daily).
Upstream is active, so local changes are structured to keep `git rebase upstream/main` cheap.

## The rule

**Keep personal values out of shared files.** Shared files (`protocol.py`, `construct_email.py`,
`config/base.yaml`) may only gain *structural* changes — a config lookup, a helper function.
The values themselves go in `config/personal.yaml`, which upstream has never heard of and
therefore can never conflict.

Same for tests: fork-specific tests live in `tests/test_personal_prompt.py`, a new file, rather
than being appended to upstream's `tests/test_protocol.py`.

**Never put personal config in `config/custom.yaml`.** CI overwrites it at runtime from the
`CUSTOM_CONFIG` GitHub variable (`.github/workflows/main.yml`), so anything committed there
works locally and is silently wiped in production. `config/personal.yaml` loads after `custom`
and is untouched.

## What diverges from upstream

| Area | Change |
|---|---|
| `protocol.py` | TL;DR prompt and prompt token budget read from config. `DEFAULT_TLDR_SYSTEM_PROMPT` / `DEFAULT_TLDR_INSTRUCTION` / `DEFAULT_MAX_PROMPT_TOKENS` hold upstream's original values, so behaviour is unchanged when the config keys are unset. |
| `construct_email.py` | `format_tldr()` — newlines to `<br>`, `**bold**` to `<strong>`. Needed because a multi-line TL;DR otherwise collapses into one paragraph. `TLDR:` label sits on its own line. |
| `config/base.yaml` | Declares `llm.max_prompt_tokens`, `llm.tldr_system_prompt`, `llm.tldr_instruction`. Required — Hydra runs in struct mode, so `.get()` on an undeclared key raises. |
| `config/default.yaml` | `- personal` appended to the defaults list. |
| `config/personal.yaml` | 8000-token budget and the structured Idea / Motivation / Method prompt. |
| `.github/workflows/main.yml` | Daily send at 12:00 UTC. |

`{lang}` in a prompt is substituted with `.replace()`, not `str.format()` — a prompt containing
LaTeX braces would otherwise raise, get swallowed by the `except` in `generate_tldr`, and
silently degrade the TL;DR to the raw abstract.

## Pulling from upstream

```bash
git fetch upstream
git stash push -u              # untracked personal.yaml must come along
git rebase upstream/main
git stash pop
```

`rerere.enabled` is on; `.github/keep-alive.txt` conflicts recur and resolve themselves after
the first time.

## Known issues (unfixed)

- `config/custom.yaml` in the repo is upstream's template (`smtp.qq.com`) and does not match the
  126.com sender, so local sends fail auth. Use `smtp.126.com:465`. Production is unaffected.
- Gmail clips at ~102 KB; blocks measure ~2.8 KB/paper, so digests past ~36 papers get truncated
  (`executor.max_paper_num` is 100).
- `format_tldr` does not HTML-escape model output — a stray `&` or `<` breaks markup.
- LaTeX (`$Q$`) from the paper source can leak into the email; the prompt does not forbid it.
