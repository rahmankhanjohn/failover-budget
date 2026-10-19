# failover-budget

Measure what DNS and GSLB failover actually costs, in the only unit that matters: what your users experience.

```
visible recovery = probe detection + remaining TTL + cache propagation
```

Most teams believe their failover takes thirty seconds because the load balancer console says so. The console measures the appliance decision. Users experience probe interval times failure threshold, plus worst-case remaining DNS TTL, plus resolver and client cache propagation. This tool adds the terms up.

## Requirements

Python 3.9+, no dependencies.

## Install and run

### Option 1: single file, no Python (Windows)

Download `failover-budget.exe` from the releases page and run it directly.

```
failover-budget.exe --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60
```

To build it yourself from source:

```
build_windows.bat
```

### Option 2: from source

```bash
git clone https://github.com/rahmankhanjohn/failover-budget.git
cd failover-budget
python3 failover_budget.py --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60
```

On Windows the launcher is `py` if `python` is not on your path:

```
py failover_budget.py --ttl 600
```

### Option 3: no install, one line

```
python -c "import urllib.request;exec(urllib.request.urlopen('https://raw.githubusercontent.com/rahmankhanjohn/failover-budget/main/failover_budget.py').read())" --ttl 600
```

## Usage

```bash
$ python3 failover_budget.py --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60
```

```
Failover budget
==============================================================
  Probe detection        15s    2.0%   5s interval x 3 failures
  Remaining TTL      14m 40s   78.4%   worst case (failure right after cache fill)
  Cache propagation      1m    17.6%   resolvers and clients beyond TTL
--------------------------------------------------------------
  User-visible recovery  15m 55s   target 1m 0s
  Result: OVER TARGET by 14m 55s
Console timestamps measure the appliance decision.
This measures what users experience.
```

Flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `--probe-interval` | 5 | health probe interval, seconds |
| `--fall-threshold` | 3 | consecutive failures before demote |
| `--ttl` | 300 | DNS TTL, worst-case remaining, seconds |
| `--cache-propagation` | 60 | resolver/client caches beyond TTL, seconds |
| `--target` | 60 | recovery target, seconds |
| `--json` | off | machine-readable output |

Exit code 0 = within target, 1 = over target. Script it:

```bash
python3 failover_budget.py --ttl 300 && echo ok || echo "failover budget blown"
```

## What each term means

**Probe detection.** How long before the load balancer notices the failure. Probe interval times fall threshold. Tune both in the pool monitor config (`inter 5s fall 3 rise 2` is a common shape).

**Remaining TTL.** Worst case is the full TTL: failure strikes just after a resolver cached the answer, and clients keep landing on the dead site until the record expires. Shorten TTL on critical records or accept the budget.

**Cache propagation.** Resolvers and clients that do not honour TTL cleanly, plus positive and negative caching layers you do not control. Measure it with a packet capture after TTL expiry rather than guessing.

## Measuring the real number (the drill)

1. Pick a maintenance window and tell the application team.
2. Power off the primary (or withdraw the route).
3. Run `failover_budget.py` with your configured values alongside a stopwatch.
4. Capture client-side behaviour after TTL expiry (packet capture or synthetic probes from outside your network).
5. Record the real number. File it. Repeat quarterly.

The budget you have never measured is a wish.

## Why this exists

Presented at bdNOG22, Cox's Bazar, November 14, 2026 — *The Failover Budget Equation: Measuring Real DNS and GSLB Recovery Time*.

Anycast solves the TTL half of the equation at BGP convergence speed, but it does not replace health awareness. Whatever your steering mechanism, measure the user-visible number, not the appliance one.

## Tests

```bash
python3 -m unittest test_failover_budget -v
```

## License

MIT
