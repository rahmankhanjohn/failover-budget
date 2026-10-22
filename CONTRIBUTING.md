# Contributing to failover-budget

Thanks for taking the time to contribute.

## What this project is

A single-file Python CLI that calculates the DNS and GSLB failover budget: probe detection + remaining TTL + cache propagation = user-visible recovery. Zero dependencies, MIT licence. The point is that an operator can run it on a laptop, understand the number, and act on it.

## Getting started

```
git clone https://github.com/rahmankhanjohn/failover-budget.git
cd failover-budget
python -m unittest test_failover_budget -v
```

All tests should pass on Python 3.9 or newer. No install step.

## Rules of the codebase

1. **No dependencies.** Standard library only. If a feature needs a third-party package, it does not go in this repo.
2. **Single file.** `failover_budget.py` is the whole tool. Keep it that way.
3. **Every feature needs a test.** Add a test in `test_failover_budget.py` that fails without your change.
4. **Exit codes matter.** 0 = within target, 1 = over target, 2 = error. Do not break this contract.
5. **Plain English in output.** Every number carries a plain sentence explaining what it means. No jargon without a gloss.
6. **No em dashes.** Use periods or commas.

## How to contribute

1. Fork the repository.
2. Create a branch: `git checkout -b feat/your-change`.
3. Make your change. Add or update tests.
4. Run the full suite: `python -m unittest test_failover_budget -v`.
5. Run the smoke tests: `python failover_budget.py --ttl 600 --target 60 --report`.
6. Open a pull request with a short description of what you changed and why.

## What we are looking for

- New measurement targets (other DNS record types, EDNS behaviour)
- Better cache-hold detection heuristics
- Additional output formats (CSV, JSON already supported via `--json`)
- Documentation improvements
- Bug reports with reproduction steps

## What we are not looking for

- New dependencies
- Rewriting the tool in another language (a Go port is tracked separately)
- Features that require network privileges beyond a DNS query

## Reporting bugs

Open a GitHub issue with:
- The command you ran
- The output you got
- The output you expected
- Your Python version and operating system

## Code of conduct

Be direct, be specific, be kind. This is a tool for operators who are already having a hard quarter. Don't make them work harder to use it.
