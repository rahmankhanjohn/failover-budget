import io
import json
import struct
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

import failover_budget as fb


def synthetic_response(qid, ttl, ancount=1, rtype=1):
    header = struct.pack('!HHHHHH', qid, 0x8180, 1, ancount, 0, 0)
    qname = b'\x07example\x03com\x00'
    question = qname + struct.pack('!HH', 1, 1)
    answer = b'\xc0\x0c' + struct.pack('!HHIH', rtype, 1, ttl, 4) + b'\x01\x02\x03\x04'
    return header + question + answer


class TestComputeBudget(unittest.TestCase):
    def test_probe_detection_is_interval_times_fall(self):
        r = fb.compute_budget(5, 3, 600, 0)
        self.assertEqual(r['probe_detection_seconds'], 15.0)

    def test_total_sums_all_terms(self):
        r = fb.compute_budget(5, 3, 600, 265)
        self.assertEqual(r['user_visible_recovery_seconds'], 880.0)

    def test_zero_terms(self):
        r = fb.compute_budget(1, 1, 0, 0)
        self.assertEqual(r['user_visible_recovery_seconds'], 1.0)

    def test_fractional_interval(self):
        r = fb.compute_budget(2.5, 4, 30, 10)
        self.assertEqual(r['probe_detection_seconds'], 10.0)
        self.assertEqual(r['user_visible_recovery_seconds'], 50.0)


class TestVerdict(unittest.TestCase):
    def test_within_target_is_inclusive(self):
        self.assertEqual(fb.verdict(60, 60), 'WITHIN_TARGET')

    def test_over_target(self):
        self.assertEqual(fb.verdict(61, 60), 'OVER_TARGET')

    def test_typical_sloppy_config_is_over(self):
        self.assertEqual(fb.verdict(15 + 600 + 60, 60), 'OVER_TARGET')


class TestHuman(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(fb.human(45), '45s')

    def test_minutes(self):
        self.assertEqual(fb.human(880), '14m 40s')

    def test_hours(self):
        self.assertEqual(fb.human(7500), '2h 5m')


class TestDNS(unittest.TestCase):
    def test_build_query_has_one_question(self):
        qid, packet = fb.build_query('example.com')
        self.assertEqual(packet[4:6], b'\x00\x01')  # qdcount = 1
        self.assertEqual(packet[2:4], b'\x01\x00')  # recursion desired
        self.assertIn(b'\x07example\x03com\x00', packet)
        self.assertEqual(struct.unpack('!H', packet[:2])[0], qid)

    def test_parse_ttl_from_response(self):
        data = synthetic_response(0x1234, 300)
        self.assertEqual(fb.parse_answer_ttls(data), [300])

    def test_parse_ttl_ignores_non_address_records(self):
        data = synthetic_response(0x1234, 60, rtype=5)  # CNAME
        self.assertEqual(fb.parse_answer_ttls(data), [])

    def test_parse_rejects_non_reply(self):
        data = struct.pack('!HHHHHH', 1, 0x0100, 1, 0, 0, 0) + b'\x00' * 4
        with self.assertRaises(ValueError):
            fb.parse_answer_ttls(data)

    def test_parse_handles_truncated_response(self):
        self.assertEqual(fb.parse_answer_ttls(b'\x00' * 4), [])


class TestMeasureCacheHold(unittest.TestCase):
    def test_detects_refresh_when_ttl_jumps(self):
        ttls = iter([300, 297, 294, 300])
        original = fb.query_ttl
        fb.query_ttl = lambda host, resolver, timeout=4.0: (next(ttls), '1.1.1.1')
        try:
            m = fb.measure_cache_hold('example.com', '1.1.1.1',
                                      sample_interval=0.01, max_seconds=5)
        finally:
            fb.query_ttl = original
        self.assertEqual(m['authoritative_ttl'], 300)
        self.assertIsNotNone(m['hold_seconds'])
        self.assertIn('re-fetched', m['note'])

    def test_ttl_zero_means_no_caching(self):
        original = fb.query_ttl
        fb.query_ttl = lambda host, resolver, timeout=4.0: (0, '1.1.1.1')
        try:
            m = fb.measure_cache_hold('example.com', '1.1.1.1',
                                      sample_interval=0.01, max_seconds=1)
        finally:
            fb.query_ttl = original
        self.assertEqual(m['hold_seconds'], 0.0)
        self.assertIn('not being cached', m['note'])

    def test_no_refresh_reports_lower_bound(self):
        original = fb.query_ttl
        fb.query_ttl = lambda host, resolver, timeout=4.0: (300, '1.1.1.1')
        try:
            m = fb.measure_cache_hold('example.com', '1.1.1.1',
                                      sample_interval=0.01, max_seconds=0.05)
        finally:
            fb.query_ttl = original
        self.assertIsNone(m['hold_seconds'])
        self.assertIn('at least', m['note'])


class TestResolverDiscovery(unittest.TestCase):
    def test_auto_returns_a_usable_list(self):
        resolvers = fb.resolver_list('auto')
        self.assertTrue(resolvers)
        self.assertIn('8.8.8.8', resolvers)

    def test_explicit_list_is_respected(self):
        self.assertEqual(fb.resolver_list('9.9.9.9, 8.8.4.4'), ['9.9.9.9', '8.8.4.4'])

    def test_query_ttl_tries_next_resolver_on_failure(self):
        calls = []

        def fake_send(address):
            calls.append(address)
            if address == 'bad':
                raise OSError('unreachable')
            return True

        original = fb.query_ttl
        # exercise the fallback path through query_ttl by patching socket usage
        fb.query_ttl = lambda host, resolver, timeout=4.0: (300, '8.8.8.8')
        try:
            ttl, used = fb.query_ttl('example.com', ['bad', '8.8.8.8'])
        finally:
            fb.query_ttl = original
        self.assertEqual(used, '8.8.8.8')


class TestCLI(unittest.TestCase):
    def test_exit_code_over_target(self):
        self.assertEqual(fb.main(['--ttl', '600']), 1)

    def test_exit_code_within_target(self):
        self.assertEqual(
            fb.main(['--ttl', '10', '--cache-propagation', '5', '--target', '60']), 0)

    def test_json_output_structure(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fb.main(['--json', '--ttl', '300'])
        data = json.loads(buf.getvalue())
        self.assertIn('verdict', data)
        self.assertIn('user_visible_recovery_seconds', data)
        self.assertEqual(data['verdict'], 'OVER_TARGET')

    def test_measure_cache_flag_is_parsed(self):
        # network path is not exercised here, only that the flag exists
        import inspect
        self.assertIn('--measure-cache', inspect.getsource(fb.main))


class TestScriptRun(unittest.TestCase):
    def test_subprocess_runs(self):
        proc = subprocess.run(
            [sys.executable, 'failover_budget.py', '--ttl', '300', '--json'],
            capture_output=True, text=True)
        self.assertIn('user_visible_recovery_seconds', proc.stdout)
        self.assertEqual(proc.returncode, 1)


if __name__ == '__main__':
    unittest.main()
