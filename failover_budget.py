#!/usr/bin/env python3
"""Failover budget: what DNS and GSLB recovery actually costs.

visible_recovery = probe_detection + remaining_ttl + cache_propagation

  probe_detection   = probe_interval x fall_threshold (when the LB notices)
  remaining_ttl     = worst case, failure right after a resolver cached
  cache_propagation = resolver and client caches beyond TTL expiry

Also measures the real cache hold of a resolver from wherever you run it,
using a minimal DNS client over UDP (no dependencies).

Exit code 0 if within target, 1 if over. --json for scripting.
"""

import argparse
import json
import random
import re
import socket
import struct
import subprocess
import sys
import time

PROBE_INTERVAL_DEFAULT = 5.0
FALL_THRESHOLD_DEFAULT = 3
TTL_DEFAULT = 300
CACHE_DEFAULT = 60
TARGET_DEFAULT = 60
RESOLVER_DEFAULT = 'auto'
HOST_DEFAULT = 'example.com'
SAMPLE_INTERVAL_DEFAULT = 3.0
MAX_SECONDS_DEFAULT = 120.0
FALLBACK_RESOLVERS = ['8.8.8.8', '1.1.1.1', '9.9.9.9']

# Plain words for each term. Written to be understood by anyone, in any language.
PLAIN = {
    'probe': 'how long until the load balancer notices',
    'ttl': 'how long clients keep the old answer',
    'cache': 'the part nobody measures',
}


def discover_resolvers():
    """Resolvers configured on this machine, plus public fallbacks."""
    found = []
    if sys.platform.startswith('win'):
        try:
            out = subprocess.run(['ipconfig', '/all'], capture_output=True,
                                 text=True, timeout=10).stdout
            for line in out.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith('dns servers'):
                    for part in stripped.split(':', 1)[-1].split(','):
                        part = part.strip()
                        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', part):
                            found.append(part)
        except Exception:
            pass
    else:
        try:
            with open('/etc/resolv.conf') as handle:
                for line in handle:
                    if line.startswith('nameserver'):
                        parts = line.split()
                        if len(parts) > 1 and re.match(r'^\d{1,3}(\.\d{1,3}){3}$', parts[1]):
                            found.append(parts[1])
        except Exception:
            pass
    ordered = []
    for item in found + FALLBACK_RESOLVERS:
        if item not in ordered:
            ordered.append(item)
    return ordered


def resolver_list(spec):
    if spec and spec != 'auto':
        return [r.strip() for r in spec.split(',') if r.strip()]
    return discover_resolvers()


# ---------------------------------------------------------------- budget

def compute_budget(probe_interval, fall_threshold, remaining_ttl, cache_propagation):
    probe_detection = probe_interval * fall_threshold
    total = probe_detection + remaining_ttl + cache_propagation
    return {
        'probe_detection_seconds': probe_detection,
        'remaining_ttl_seconds': float(remaining_ttl),
        'cache_propagation_seconds': float(cache_propagation),
        'user_visible_recovery_seconds': total,
    }


def verdict(total_seconds, target_seconds):
    return 'WITHIN_TARGET' if total_seconds <= target_seconds else 'OVER_TARGET'


def human(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return '%ds' % seconds
    mins, secs = divmod(seconds, 60)
    if mins < 60:
        return '%dm %ds' % (mins, secs)
    hours, mins = divmod(mins, 60)
    return '%dh %dm' % (hours, mins)


def render(result, probe_interval, fall_threshold, target_seconds):
    total = result['user_visible_recovery_seconds']
    lines = []
    lines.append('Failover budget')
    lines.append('=' * 62)
    rows = [
        ('Probe detection', '%gs interval x %d failures' % (probe_interval, fall_threshold),
         result['probe_detection_seconds'], PLAIN['probe']),
        ('Remaining TTL', 'worst case, just after a cache fill',
         result['remaining_ttl_seconds'], PLAIN['ttl']),
        ('Cache propagation', 'resolvers and clients beyond TTL',
         result['cache_propagation_seconds'], PLAIN['cache']),
    ]
    for name, note, value, plain in rows:
        pct = (value / total * 100) if total else 0
        lines.append('  %-20s %9s  %5.1f%%   %s' % (name, human(value), pct, note))
        lines.append('  %-40s%s' % ('', plain))
    lines.append('-' * 62)
    lines.append('  %-20s %9s   target %s' % ('User-visible recovery', human(total), human(target_seconds)))
    if verdict(total, target_seconds) == 'WITHIN_TARGET':
        lines.append('  Result: WITHIN TARGET (%s of budget left)' % human(target_seconds - total))
    else:
        lines.append('  Result: OVER TARGET by %s' % human(total - target_seconds))
    lines.append('')
    lines.append('Console timestamps measure the appliance decision.')
    lines.append('This measures what users experience.')
    return '\n'.join(lines)


def report_line(result, probe_interval, fall_threshold, target_seconds, measured=None):
    """One line a person can paste into a runbook, a status report or a ticket."""
    total = result['user_visible_recovery_seconds']
    verdict_text = ('within target' if verdict(total, target_seconds) == 'WITHIN_TARGET'
                    else 'over target by %s' % human(total - target_seconds))
    parts = [
        'Failover budget: %s user-visible recovery against a %s target (%s).'
        % (human(total), human(target_seconds), verdict_text),
        'Breakdown: probe %s, TTL %s, cache %s.'
        % (human(result['probe_detection_seconds']),
           human(result['remaining_ttl_seconds']),
           human(result['cache_propagation_seconds'])),
    ]
    if measured:
        if measured.get('hold_seconds') is not None:
            parts.append('Cache hold measured at %s on %s: %s.'
                         % (measured['host'], measured['resolver'],
                            human(measured['hold_seconds'])))
        else:
            parts.append('Cache hold measured at %s on %s: at least %s.'
                         % (measured['host'], measured['resolver'],
                            human(measured['authoritative_ttl'])))
    parts.append('Calculated %s.' % time.strftime('%Y-%m-%d'))
    parts.append('Tool: https://github.com/rahmankhanjohn/failover-budget')
    return ' '.join(parts)


# ---------------------------------------------------------------- minimal DNS client

def build_query(host, qtype=1, qid=None):
    if qid is None:
        qid = random.randint(0, 65535)
    header = struct.pack('!HHHHHH', qid, 0x0100, 1, 0, 0, 0)
    qname = b''
    for label in host.rstrip('.').split('.'):
        qname += bytes([len(label)]) + label.encode('idna')
    qname += b'\x00'
    return qid, header + qname + struct.pack('!HH', qtype, 1)


def _skip_name(data, off):
    while off < len(data):
        length = data[off]
        if length == 0:
            return off + 1
        if length & 0xC0 == 0xC0:
            return off + 2
        off += 1 + length
    return off


def parse_answer_ttls(data):
    """Return TTLs of A/AAAA answers in a DNS response."""
    if len(data) < 12:
        return []
    _id, flags, qdcount, ancount, _ns, _ar = struct.unpack('!HHHHHH', data[:12])
    if not flags & 0x8000:
        raise ValueError('response is not a DNS reply')
    off = 12
    for _ in range(qdcount):
        off = _skip_name(data, off) + 4
    ttls = []
    for _ in range(ancount):
        if off + 10 > len(data):
            break
        off = _skip_name(data, off)
        rtype, rclass, ttl, rdlen = struct.unpack('!HHIH', data[off:off + 10])
        off += 10
        if rtype in (1, 28) and rclass == 1:
            ttls.append(ttl)
        off += rdlen
    return ttls


def query_ttl(host, resolver, timeout=4.0):
    """Query one resolver for the lowest A/AAAA TTL. resolver may be a list."""
    candidates = resolver if isinstance(resolver, (list, tuple)) else [resolver]
    last_error = None
    for address in candidates:
        try:
            qid, packet = build_query(host)
            family = socket.AF_INET6 if ':' in address else socket.AF_INET
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                sock.sendto(packet, (address, 53))
                data, _ = sock.recvfrom(4096)
            ttls = parse_answer_ttls(data)
            if not ttls:
                last_error = ValueError('no A or AAAA answer from %s' % address)
                continue
            return min(ttls), address
        except Exception as exc:
            last_error = exc
    raise last_error if last_error else ValueError('no resolver answered')


PUBLIC_RESOLVERS = {'8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1', '9.9.9.9', '149.112.112.112',
                     '208.67.222.222', '208.67.220.220'}


def measure_cache_hold(host=HOST_DEFAULT, resolver=RESOLVER_DEFAULT,
                       sample_interval=SAMPLE_INTERVAL_DEFAULT, max_seconds=MAX_SECONDS_DEFAULT,
                       progress=None):
    """Observe how long a resolver holds an answer for host.

    TTLs decay while cached. When the entry expires, the resolver re-fetches
    and the TTL jumps back up. That moment is the cache hold.

    Public resolvers are anycast, so consecutive queries can land on different
    edges with independent cache state. The first reset seen may then be an
    artefact rather than a real expiry, so the measurement needs a run long
    enough to see the decay continue past the reset.
    """
    candidates = resolver_list(resolver)
    start = time.monotonic()
    first_ttl, used = query_ttl(host, candidates)
    if first_ttl == 0:
        return {'host': host, 'resolver': used, 'authoritative_ttl': 0,
                'hold_seconds': 0.0, 'samples': 1, 'anycast': used in PUBLIC_RESOLVERS,
                'note': 'resolver returned TTL 0, this record is not being cached here'}
    samples = 1
    previous = first_ttl
    elapsed = 0.0
    best_reset = None
    while elapsed < max_seconds:
        time.sleep(sample_interval)
        elapsed = time.monotonic() - start
        ttl, _ = query_ttl(host, [used])
        samples += 1
        if progress:
            progress(elapsed, ttl)
        if ttl > previous:
            if best_reset is None:
                best_reset = elapsed
            # keep sampling: a real expiry produces a full TTL, an anycast
            # artefact usually shows a partial value
            if ttl >= first_ttl * 0.95:
                hold = elapsed
                break
        else:
            previous = ttl
    else:
        hold = None
    if hold is None and best_reset is not None:
        hold = best_reset
    result = {'host': host, 'resolver': used, 'authoritative_ttl': first_ttl,
              'hold_seconds': round(hold, 1) if hold is not None else None,
              'samples': samples, 'anycast': used in PUBLIC_RESOLVERS}
    if hold is None:
        result['note'] = ('no refresh observed within %.0fs, the hold is at least that long'
                          % max_seconds)
    else:
        result['note'] = 'cache entry expired and was re-fetched'
        propagation = max(0.0, hold - first_ttl)
        result['propagation_seconds'] = round(propagation, 1)
    return result


def render_measurement(m):
    lines = []
    lines.append('Cache hold measurement')
    lines.append('=' * 62)
    lines.append('  Target        %s' % m['host'])
    lines.append('  Resolver      %s' % m['resolver'])
    lines.append('  Declared TTL  %d seconds' % m['authoritative_ttl'])
    if m.get('hold_seconds') is None:
        lines.append('  Observed hold  at least %d seconds' % m['authoritative_ttl'])
    else:
        lines.append('  Observed hold  %s' % human(m['hold_seconds']))
    if m.get('propagation_seconds') is not None:
        lines.append('  Cache propagation term  %s  (hold minus declared TTL)'
                     % human(m['propagation_seconds']))
    lines.append('  Samples       %d' % m['samples'])
    lines.append('  Note          %s' % m['note'])
    if m.get('anycast'):
        lines.append('  Warning       %s is an anycast public resolver. Edges hold answers'
                     % m['resolver'])
        lines.append('                independently, so the observed hold can be short.')
        lines.append('                Measure against the resolver your users really use.')
    lines.append('')
    lines.append('Run this from the network whose users you care about.')
    lines.append('Your resolver is not their resolver.')
    return '\n'.join(lines)


# ---------------------------------------------------------------- interactive

def interactive():
    print('=' * 62)
    print('Failover budget calculator')
    print('=' * 62)
    print('Press Enter to accept the default shown in brackets.')
    print()

    def ask(label, default, cast=float):
        try:
            raw = input('%s [%s]: ' % (label, default)).strip()
            if not raw:
                return default
            return cast(raw)
        except ValueError:
            print('  not a number, using %s' % default)
            return default

    def ask_yes(label):
        try:
            return input('%s [y/N]: ' % label).strip().lower().startswith('y')
        except (EOFError, KeyboardInterrupt):
            return False

    interval = ask('Health probe interval, seconds', PROBE_INTERVAL_DEFAULT)
    fall = ask('Failures before demote', FALL_THRESHOLD_DEFAULT, int)
    ttl = ask('DNS TTL, seconds', TTL_DEFAULT, int)
    cache = ask('Cache propagation beyond TTL, seconds', CACHE_DEFAULT)
    target = ask('Recovery target, seconds', TARGET_DEFAULT)

    measured = None
    if ask_yes('Measure the real cache hold from this machine'):
        host = input('Hostname to probe [%s]: ' % HOST_DEFAULT).strip() or HOST_DEFAULT
        resolver = input('Resolver IP or comma list [auto, use my system DNS]: ').strip() or 'auto'
        print('  Probing, this takes up to a couple of minutes. Keep this window open.')
        try:
            measured = measure_cache_hold(host, resolver)
        except Exception as exc:
            print('  measurement failed: %s' % exc)
        if measured:
            print()
            print(render_measurement(measured))
            if measured['hold_seconds']:
                cache = float(measured['hold_seconds'])
                print('  Using the measured hold as the cache propagation term.')
                print()

    result = compute_budget(interval, fall, ttl, cache)
    result['target_seconds'] = target
    result['verdict'] = verdict(result['user_visible_recovery_seconds'], target)
    print(render(result, interval, fall, target))
    print('Written down is measured. Remembered is a wish.')
    print()
    try:
        input('Press Enter to close...')
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------- cli

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        interactive()
        return 0
    parser = argparse.ArgumentParser(
        description='Calculate the failover budget: probe + TTL + cache = user-visible recovery.')
    parser.add_argument('--probe-interval', type=float, default=PROBE_INTERVAL_DEFAULT,
                        help='health probe interval in seconds (default: 5)')
    parser.add_argument('--fall-threshold', type=int, default=FALL_THRESHOLD_DEFAULT,
                        help='consecutive probe failures before demote (default: 3)')
    parser.add_argument('--ttl', type=int, default=TTL_DEFAULT,
                        help='DNS TTL in seconds, worst case remaining (default: 300)')
    parser.add_argument('--cache-propagation', type=float, default=CACHE_DEFAULT,
                        help='resolver/client cache propagation beyond TTL, seconds (default: 60)')
    parser.add_argument('--target', type=float, default=TARGET_DEFAULT,
                        help='recovery target in seconds (default: 60)')
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    parser.add_argument('--report', action='store_true',
                        help='one paste-ready line for a runbook, status report or ticket')
    parser.add_argument('--measure-cache', metavar='HOST', nargs='?',
                        const=HOST_DEFAULT,
                        help='measure the real cache hold of a resolver and exit')
    parser.add_argument('--resolver', default=RESOLVER_DEFAULT,
                        help='resolver IP or comma separated list for the measurement, '
                             'auto uses the resolvers configured on this machine (default: auto)')
    parser.add_argument('--sample-interval', type=float, default=SAMPLE_INTERVAL_DEFAULT,
                        help='seconds between probes during measurement (default: 3)')
    parser.add_argument('--max-seconds', type=float, default=MAX_SECONDS_DEFAULT,
                        help='give up measuring after this long (default: 120)')
    args = parser.parse_args(argv)

    measured = None
    if args.measure_cache:
        try:
            measured = measure_cache_hold(args.measure_cache, args.resolver,
                                          args.sample_interval, args.max_seconds)
        except Exception as exc:
            print('measurement failed: %s' % exc, file=sys.stderr)
            return 2
        if args.report:
            pass
        elif args.json:
            print(json.dumps(measured, indent=2))
        else:
            print(render_measurement(measured))
        if not args.report:
            return 0

    if args.probe_interval <= 0 or args.fall_threshold < 1:
        parser.error('probe interval must be > 0 and fall threshold >= 1')
    if args.ttl < 0 or args.cache_propagation < 0:
        parser.error('ttl and cache-propagation must be >= 0')

    result = compute_budget(args.probe_interval, args.fall_threshold, args.ttl, args.cache_propagation)
    result['target_seconds'] = args.target
    result['verdict'] = verdict(result['user_visible_recovery_seconds'], args.target)

    if args.report:
        print(report_line(result, args.probe_interval, args.fall_threshold,
                          args.target, measured))
    elif args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result, args.probe_interval, args.fall_threshold, args.target))
    return 0 if result['verdict'] == 'WITHIN_TARGET' else 1


if __name__ == '__main__':
    sys.exit(main())
