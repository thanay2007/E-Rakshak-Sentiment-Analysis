"""Authentication, authorization and hardening primitives.

  roles      the three-rank hierarchy and `at_least` comparisons
  passwords  scrypt hashing / verification
  tokens     JWT issue + verify
  ssrf       outbound-request guard for the OSINT fetchers
  ratelimit  in-process token-bucket limiter
  crypto     envelope encryption for biometric templates at rest
"""
