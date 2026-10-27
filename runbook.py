# Operational runbook content for failover-budget tool.
# Append to failover_budget.py or use as a module.

RUNBOOK = r'''
==============================================================================
OPERATOR RUNBOOK: Diagnosing DNS and GSLB Failover
==============================================================================

Step 1: What is DNS actually returning?
------------------------------------------------------------------------------
  Command:  dig example.com
  Look for: the ANSWER SECTION, the TTL value, the status (NOERROR vs NXDOMAIN)

  If the answer shows the old IP after a failover:
    -> The resolver still has the cached answer. TTL has not expired.
    -> This is the remaining_ttl term in the budget.

  If the answer shows the new IP but clients still hit the old site:
    -> Resolver cache is stale beyond TTL. This is the cache_propagation term.
    -> Run: failover-budget --measure-cache example.com

  If the answer shows NXDOMAIN or SERVFAIL:
    -> DNS itself is broken. Check authoritative servers first.
    -> This is not a failover budget problem. This is a DNS outage.

Step 2: What does the resolver think the TTL is?
------------------------------------------------------------------------------
  Command:  dig @resolver.example example.com
  Look for: the TTL in the ANSWER SECTION

  Compare the resolver TTL to the authoritative TTL.
  If resolver TTL > authoritative TTL:
    -> The resolver is caching longer than configured. Common with some ISPs.
    -> Your remaining_ttl term is larger than you think.

  If resolver TTL < authoritative TTL:
    -> The resolver is respecting the TTL. Good.
    -> But clients may still cache beyond the resolver.

  Measure the real cache hold:
    Command:  failover-budget --measure-cache example.com --resolver 1.1.1.1
    This probes the resolver repeatedly until the answer changes.

Step 3: Is the application actually responding?
------------------------------------------------------------------------------
  Command:  curl -I https://example.com
  Look for: HTTP status code, response time, TLS handshake

  200 OK in under 2s:
    -> Application is up. Problem is DNS or routing, not the app.

  5xx or timeout:
    -> Application is down or overloaded. Check the origin directly.

  Connection refused:
    -> Nothing is listening. Check the service, not DNS.

  TLS handshake failure:
    -> Certificate issue. Check expiry, SAN, and intermediate chain.

Step 4: Is traffic reaching the right place?
------------------------------------------------------------------------------
  Command:  tcpdump -ni any port 53
  Look for: DNS queries and responses on port 53

  Queries going to the old resolver:
    -> Clients are still using the cached resolver. Wait for TTL.

  Queries going to the new resolver but getting old answers:
    -> Resolver cache is stale. This is the cache_propagation term.

  No queries at all:
    -> Clients are not retrying. Check client DNS config and retry logic.

  Queries with SERVFAIL responses:
    -> Upstream resolver is failing. Check resolver health.

Step 5: Is the health check lying?
------------------------------------------------------------------------------
  HAProxy example:
    inter 3s, fall 3, rise 2

  If inter is 1s and fall is 1:
    -> One slow response demotes the member. Deploys look like failures.
    -> Fix: inter 3s, fall 3, rise 2. Shallow check: process up, port accepts, 200.

  If inter is 30s and fall is 10:
    -> A dead member receives traffic for 5 minutes.
    -> Fix: inter 3s, fall 3. Dead members are caught in 9 seconds, not 5 minutes.

  If the health check queries the database:
    -> A database blip demotes every server at once.
    -> Fix: shallow check. Process up, port accepts, 200. Deep checks belong in monitoring.

  Check the logs:
    Command:  grep "health check" /var/log/haproxy.log | tail -20
    Look for: repeated UP/DOWN transitions, false positives

Step 6: Calculate the budget
------------------------------------------------------------------------------
  Command:  failover-budget --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60 --target 60

  The output shows which term dominates. Fix the biggest one first.

  If TTL is the biggest term:
    -> Reduce TTL on dynamic records. Keep long TTLs on stable ones.
    -> Trade-off: more DNS query load. Make it visible.

  If cache_propagation is the biggest term:
    -> Measure the real cache hold: failover-budget --measure-cache example.com
    -> Some resolvers cache beyond TTL. Anycast removes this term at the routing layer.

  If probe_detection is the biggest term:
    -> Reduce inter and fall. But not too tight (see Step 5).
    -> inter 3s, fall 3 is the starting point.

Step 7: Run the drill
------------------------------------------------------------------------------
  1. Pick a maintenance window. Notify the application team.
  2. Power off the primary or withdraw the route. No standby needed.
  3. Watch the clock: probe detection to first client success.
  4. Capture client behavior after TTL expiry (packet capture on port 53).
  5. Write the number down. One page. That is your recovery time.

  Do this quarterly. Put it on the calendar.

==============================================================================
DECISION TREE: What is failing right now?
==============================================================================

  Symptom: Users report the site is down.
    |
    +-- Is DNS returning the correct IP?
    |     dig example.com
    |     |
    |     +-- NO (old IP) --> TTL has not expired. Wait or reduce TTL.
    |     +-- YES (new IP) --> Go to next check.
    |
    +-- Is the application responding?
    |     curl -I https://example.com
    |     |
    |     +-- NO (5xx/timeout) --> Application is down. Check origin.
    |     +-- YES (200 OK) --> Go to next check.
    |
    +-- Is traffic reaching the new site?
    |     tcpdump -ni any port 53
    |     |
    |     +-- NO queries --> Clients not retrying. Check client DNS config.
    |     +-- Queries to old resolver --> Resolver cache stale. Wait or flush.
    |     +-- Queries to new resolver, old answer --> Resolver ignoring TTL.
    |
    +-- Did the failover actually happen?
          Check LB logs: grep "health check" /var/log/haproxy.log
          |
          +-- Member never demoted --> Health check too loose. Fix inter/fall.
          +-- Member demoted but traffic still flows --> Health check lied.
          +-- Member demoted, traffic stopped --> Failover worked. Problem is DNS/cache.

==============================================================================
COMMON MISTAKES AND HOW TO AVOID THEM
==============================================================================

  Mistake 1: Trusting the console's 30-second failover time.
    Fix: Measure user-visible recovery, not appliance decision time.

  Mistake 2: Setting TTL to 300s "because that is the default."
    Fix: Measure the real cache hold. Some resolvers cache beyond TTL.

  Mistake 3: Health check queries the database.
    Fix: Shallow check. Process up, port accepts, 200. Deep checks in monitoring.

  Mistake 4: Tuning health checks too tight (inter 1s, fall 1).
    Fix: inter 3s, fall 3, rise 2. Deploys will not trigger false failovers.

  Mistake 5: Not writing down the recovery number.
    Fix: One page per drill. Date, method, result. Compare over time.

  Mistake 6: Assuming Anycast removes all DNS dependency.
    Fix: Anycast removes the TTL term at routing. It does not replace health awareness.

==============================================================================
'''


def render_runbook():
    """Print the operator runbook."""
    print(RUNBOOK)


def render_diagnose(symptom=None):
    """Print a symptom-based diagnosis guide."""
    print("=" * 72)
    print("DIAGNOSTIC GUIDE: What is failing right now?")
    print("=" * 72)
    print()
    print("Symptom: Users report the site is down or slow.")
    print()
    print("  1. Check DNS answer:")
    print("     $ dig example.com")
    print("     Look for: ANSWER SECTION, TTL value, status (NOERROR/NXDOMAIN)")
    print()
    print("     If old IP returned -> TTL has not expired. Wait or reduce TTL.")
    print("     If new IP returned -> DNS is fine. Check application.")
    print("     If NXDOMAIN/SERVFAIL -> DNS is broken. Check authoritative.")
    print()
    print("  2. Check application:")
    print("     $ curl -I https://example.com")
    print("     Look for: HTTP status, response time, TLS handshake")
    print()
    print("     If 200 OK -> Application is up. Problem is DNS or routing.")
    print("     If 5xx/timeout -> Application is down. Check origin.")
    print("     If connection refused -> Nothing listening. Check service.")
    print()
    print("  3. Check traffic flow:")
    print("     $ tcpdump -ni any port 53")
    print("     Look for: DNS queries and responses")
    print()
    print("     No queries -> Clients not retrying. Check client DNS config.")
    print("     Queries to old resolver -> Resolver cache stale. Wait or flush.")
    print("     SERVFAIL responses -> Upstream resolver failing. Check resolver.")
    print()
    print("  4. Check load balancer:")
    print("     $ grep 'health check' /var/log/haproxy.log | tail -20")
    print("     Look for: UP/DOWN transitions, false positives")
    print()
    print("     Member never demoted -> Health check too loose.")
    print("     Member demoted, traffic still flows -> Health check lied.")
    print("     Member demoted, traffic stopped -> Failover worked. Problem is DNS.")
    print()
    print("  5. Measure the budget:")
    print("     $ failover-budget --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60 --target 60")
    print("     Look for: which term dominates. Fix the biggest one first.")
    print()
    print("  6. Measure real cache hold:")
    print("     $ failover-budget --measure-cache example.com --resolver 1.1.1.1")
    print("     Look for: how long the resolver actually caches beyond TTL.")
    print()
    print("=" * 72)
    print("Full runbook: failover-budget --runbook")
    print("=" * 72)
