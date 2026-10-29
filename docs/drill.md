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

## Restore

Bring the primary back, verify `dig` returns it, verify client 200s, close the window. Keep the logs with the drill row.
