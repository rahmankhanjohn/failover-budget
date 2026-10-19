#!/usr/bin/env python3
"""Failover budget: what DNS and GSLB recovery actually costs.

visible_recovery = probe_detection + remaining_ttl + cache_propagation

  probe_detection   = probe_interval x fall_threshold (when the LB notices)
  remaining_ttl     = worst case, failure right after a resolver cached
  cache_propagation = resolver and client caches beyond TTL expiry

Exit code 0 if within target, 1 if over. --json for scripting.
"""

import argparse
import json
import sys

PROBE_INTERVAL_DEFAULT = 5.0
FALL_THRESHOLD_DEFAULT = 3
TTL_DEFAULT = 300
CACHE_DEFAULT = 60
TARGET_DEFAULT = 60


def compute_budget(probe_interval, fall_threshold, remaining_ttl, cache_propagation):
    probe_detection = probe_interval * fall_threshold
    total = probe_detection + remaining_ttl + cache_propagation
    return {
        "probe_detection_seconds": probe_detection,
        "remaining_ttl_seconds": float(remaining_ttl),
        "cache_propagation_seconds": float(cache_propagation),
        "user_visible_recovery_seconds": total,
    }


def verdict(total_seconds, target_seconds):
    if total_seconds <= target_seconds:
        return "WITHIN_TARGET"
    return "OVER_TARGET"


def human(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    mins, secs = divmod(seconds, 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}m"


def render(result, probe_interval, fall_threshold, target_seconds):
    total = result["user_visible_recovery_seconds"]
    lines = []
    lines.append("Failover budget")
    lines.append("=" * 62)
    rows = [
        (
            "Probe detection",
            f"{probe_interval:g}s interval x {fall_threshold} failures",
            result["probe_detection_seconds"],
        ),
        (
            "Remaining TTL",
            "worst case (failure right after cache fill)",
            result["remaining_ttl_seconds"],
        ),
        (
            "Cache propagation",
            "resolvers and clients beyond TTL",
            result["cache_propagation_seconds"],
        ),
    ]
    for name, note, value in rows:
        pct = (value / total * 100) if total else 0
        lines.append(
            f"  {name:<20} {human(value):>9}  {pct:5.1f}%   {note}"
        )
    lines.append("-" * 62)
    lines.append(
        f"  {'User-visible recovery':<20} {human(total):>9}"
        f"   target {human(target_seconds)}"
    )
    v = verdict(total, target_seconds)
    if v == "WITHIN_TARGET":
        lines.append(f"  Result: WITHIN TARGET ({human(target_seconds - total)} of budget left)")
    else:
        lines.append(f"  Result: OVER TARGET by {human(total - target_seconds)}")
    lines.append("")
    lines.append("Console timestamps measure the appliance decision.")
    lines.append("This measures what users experience.")
    return "\n".join(lines)


def interactive():
    """Double-click mode: prompt for values, show the result, wait before closing."""
    print("=" * 62)
    print("Failover budget calculator")
    print("=" * 62)
    print("Press Enter to accept the default shown in brackets.")
    print()

    def ask(label, default, cast=float):
        try:
            raw = input(f"{label} [{default}]: ").strip()
            if not raw:
                return default
            return cast(raw)
        except ValueError:
            print(f"  not a number, using {default}")
            return default

    interval = ask("Health probe interval, seconds", PROBE_INTERVAL_DEFAULT)
    fall = ask("Failures before demote", FALL_THRESHOLD_DEFAULT, int)
    ttl = ask("DNS TTL, seconds", TTL_DEFAULT, int)
    cache = ask("Cache propagation beyond TTL, seconds", CACHE_DEFAULT)
    target = ask("Recovery target, seconds", TARGET_DEFAULT)

    result = compute_budget(interval, fall, ttl, cache)
    result["target_seconds"] = target
    result["verdict"] = verdict(result["user_visible_recovery_seconds"], target)
    print()
    print(render(result, interval, fall, target))
    print("Written down is measured. Remembered is a wish.")
    print()
    try:
        input("Press Enter to close...")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        interactive()
        return 0
    parser = argparse.ArgumentParser(
        description="Calculate the failover budget: probe + TTL + cache = user-visible recovery."
    )
    parser.add_argument(
        "--probe-interval", type=float, default=PROBE_INTERVAL_DEFAULT,
        help="health probe interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--fall-threshold", type=int, default=FALL_THRESHOLD_DEFAULT,
        help="consecutive probe failures before demote (default: 3)",
    )
    parser.add_argument(
        "--ttl", type=int, default=TTL_DEFAULT,
        help="DNS TTL in seconds, worst case remaining (default: 300)",
    )
    parser.add_argument(
        "--cache-propagation", type=float, default=CACHE_DEFAULT,
        help="resolver/client cache propagation beyond TTL, seconds (default: 60)",
    )
    parser.add_argument(
        "--target", type=float, default=TARGET_DEFAULT,
        help="recovery target in seconds (default: 60)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.probe_interval <= 0 or args.fall_threshold < 1:
        parser.error("probe interval must be > 0 and fall threshold >= 1")
    if args.ttl < 0 or args.cache_propagation < 0:
        parser.error("ttl and cache-propagation must be >= 0")

    result = compute_budget(
        args.probe_interval, args.fall_threshold, args.ttl, args.cache_propagation
    )
    result["target_seconds"] = args.target
    result["verdict"] = verdict(result["user_visible_recovery_seconds"], args.target)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            render(
                result,
                args.probe_interval,
                args.fall_threshold,
                args.target,
            )
        )
    return 0 if result["verdict"] == "WITHIN_TARGET" else 1


if __name__ == "__main__":
    sys.exit(main())
