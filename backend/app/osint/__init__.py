"""OSINT / investigation toolkit for E-Rakshak (SENTINEL).

A self-contained set of analyst tools that sit alongside the live threat feed:

  • image_analysis   — EXIF / GPS / manipulation forensics on an uploaded image
  • media_intel      — perceptual-hash reverse search: where else did this image
                       appear, which accounts posted it, is the person a public figure
  • username_lookup  — cross-platform handle lookup: reads the real profile from
                       each platform's API, then correlates them (name, photo
                       hash, bio, links) into one identity plus related accounts
  • pr_analysis      — coordinated inauthentic PR / astroturf campaign detection
  • sleuth           — account dossier from the monitored corpus, consumed by
                       face_intel when a matched suspect has known handles

Everything degrades gracefully with zero API keys (the house style of this repo):
network-dependent checks time out into "unknown" rather than failing the request.
"""
