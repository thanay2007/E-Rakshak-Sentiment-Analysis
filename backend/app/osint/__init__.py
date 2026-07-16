"""OSINT / investigation toolkit for E-Rakshak (SENTINEL).

A self-contained set of analyst tools that sit alongside the live threat feed:

  • image_analysis   — EXIF / GPS / manipulation forensics on an uploaded image
  • media_intel      — perceptual-hash reverse search: where else did this image
                       appear, which accounts posted it, is the person a public figure
  • username_lookup  — Sherlock-style cross-platform handle enumeration
  • url_analysis     — link safety: redirect unwrapping + phishing heuristics
  • comment_analysis — sentiment of a post's comments + bot-account detection
  • pr_analysis      — coordinated inauthentic PR / astroturf campaign detection
  • sleuth           — one-shot account dossier tying all of the above together

Everything degrades gracefully with zero API keys (the house style of this repo):
network-dependent checks time out into "unknown" rather than failing the request.
"""
