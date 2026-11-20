# The fifteen minute drill: exact procedure

Run this quarterly. It produces the one number your runbook is missing: how long your users actually wait after a failover.

## Pre-drill checklist

- [ ] Maintenance window booked, application team notified
- [ ] Access to the primary: power control or route withdrawal
- [ ] A client machine on the user side of the resolver (office LAN or VPN)
- [ ] Packet capture running on that client (root/admin)
- [ ] This file open, timestamps noted

## Commands, in order

### 1. Record the steady state (before touching anything)

```
dig +noall +answer yourapp.example.com
```

Windows PowerShell:

```
Resolve-DnsName yourapp.example.com
```

Expected: the primary IP with your configured TTL. Write down the TTL and the answer.

```
failover-budget --measure-cache yourapp.example.com --resolver <user-resolver-IP>
```

Expected: the real cache hold of the resolver your users actually use. This is your cache_propagation term, observed rather than guessed.

### 2. Start the clock and kill the primary

Note the wall-clock time: `T0`. Power off the primary or withdraw its route.

### 3. Watch the resolver answer flip

From the client side, in a loop:

Linux/macOS:

```
while true; do echo "$(date +%H:%M:%S) $(dig +short yourapp.example.com @<resolver>)"; sleep 2; done | tee resolver-flip.log
```

Windows PowerShell:

```
while ($true) { "$(Get-Date -Format HH:mm:ss) $((Resolve-DnsName yourapp.example.com -Server <resolver> -Type A).IPAddress)" ; Start-Sleep 2 } | Tee-Object resolver-flip.log
```

Expected: the old IP repeats until the TTL expires, then the new IP appears. The timestamp of the first new answer is `T1`.

**T1 minus T0 is your remaining_ttl term, observed.**

### 4. Watch clients stop hitting the dead site

The packet capture is already running. On the client:

```
tcpdump -ni any host <old-ip> and not port 22
```

Expected: connections to the old IP continue after `T1` (client caches live past the resolver answer). They stop at `T2`.

**T2 minus T1 is your cache_propagation term, observed.**

### 5. Measure first client success

```
while true; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 https://yourapp.example.com)
  echo "$(date +%H:%M:%S) $code"
  [ "$code" = "200" ] && break
  sleep 1
done | tee client-success.log
```

Windows PowerShell:

```
while ($true) { $code = (Invoke-WebRequest -Uri https://yourapp.example.com -Method Head -ErrorAction SilentlyContinue).StatusCode; "$(Get-Date -Format HH:mm:ss) $code"; if ($code -eq 200) { break }; Start-Sleep 1 } | Tee-Object client-success.log
```

The first 200 is `T3`. **T3 minus T0 is your user-visible recovery. This is the number.**

### 6. Compute the budget and compare

```
failover-budget --probe-interval <your-interval> --fall-threshold <your-threshold> --ttl <your-ttl> --cache-propagation <T2-T1> --target <your-target> --report
```

Use the measured cache propagation, not the default. The report line goes in the log.

### 7. Write the row

One line in the drill log (template below). One page per drill. Compare across quarters.

## Reading the result

| Observation | Dominant term | First lever |
|---|---|---|
| T1-T0 close to full TTL | remaining_ttl | Shorten TTL on this record; measure query-load cost first |
| T2-T1 large even with short TTL | cache_propagation | Find resolvers that ignore TTL; consider anycast for the routing layer |
| T3-T2 long after DNS flipped | probe_detection or app | Check LB demote time in logs; verify shallow health check |
| Flip never happened | not a DNS problem | Health check never demoted: loosen fall threshold or fix probe target |

## What your recovery number means for your SLO

99.9% availability allows 526 minutes of downtime per year. Divide that by your measured user-visible recovery time (T3 minus T0) to find how many failovers you can afford:

- 2m 16s recovery → about 84 failovers per year (one every 4-5 days)
- 11m 15s recovery → about 46 failovers per year
- 1m 29s recovery → about 407 failovers per year

Cutting TTL — usually the largest term — shrinks recovery and raises the number of failovers your budget can absorb. This turns an abstract SLO ("99.9%") into a concrete operational limit you can track drill by drill.

## SRE concepts behind the failover budget

**SLI (Service Level Indicator):** user-visible recovery time — `T3 minus T0`, how long your users actually wait after a failover.

**SLO (Service Level Objective):** your internal reliability target, e.g. 99.9% availability. This is what your engineering team aims for.

**SLA (Service Level Agreement):** an external contract with customers, often with penalties if missed. Your SLO should be stricter than your SLA so you have margin.

**Error budget:** the allowable unreliability derived from your SLO. 99.9% availability leaves 0.1% (526 minutes per year) of error budget. If you burn through it, you pause feature work to fix reliability.

**How the failover budget maps to SRE:** your measured user-visible recovery is the SLI. Your availability target is the SLO. The number of failovers you can afford per year is your error budget in practice. The drill measures the SLI; the log tracks the trend against the SLO.

## Restore

Bring the primary back, verify `dig` returns it, verify client 200s, close the window. Keep the logs with the drill row.

Windows PowerShell restore check:

```
Resolve-DnsName yourapp.example.com
```
