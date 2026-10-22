# Security Policy

## Supported Versions

Only the latest release is supported. Security fixes are applied to `main` and released as a new version.

| Version | Supported |
|---------|-----------|
| Latest (v1.4+) | Yes |
| Older | No |

## Reporting a Vulnerability

If you find a security issue, please report it privately.

- **Email:** open an issue on GitHub marked as private, or contact the maintainer through the GitHub profile
- **Do not** open a public issue for a security vulnerability

Please include:
- A description of the issue
- Steps to reproduce
- The version you tested
- The impact you believe it has

You will receive a response within 7 days. If the issue is confirmed, a fix will be released as a new version and the vulnerability will be disclosed after the fix is available.

## Scope

This tool makes outbound UDP port 53 queries to DNS resolvers that you specify. It does not store credentials, does not make any other network calls, and does not modify any files or system configuration. The attack surface is limited to DNS response parsing, which uses Python's standard library `struct` module.

## Known limitations

- No TLS for DNS queries (DNS over HTTPS is not supported in v1.x)
- No authentication on the resolver (the resolver is assumed to be trusted)
- The cache-hold measurement makes repeated DNS queries to a target host, which generates traffic on your resolver