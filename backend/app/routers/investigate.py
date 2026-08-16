"""OSINT / investigation toolkit endpoints.

Covers the analyst-tool features:
  image forensics, reverse-image source tracing, people finding (+ famous-
  personality filter), cross-platform username lookup with account correlation,
  and fake-PR campaign detection.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session
from app.database import get_session

from app.osint.explain import explain_report
from app.osint.face_intel import identify_faces, identify_media
from app.osint.image_analysis import analyze_image
from app.osint.media_intel import find_person, reverse_lookup
from app.osint.post_media import analyze_from_post, analyze_from_url
from app.osint.pr_analysis import detect_pr_campaigns
from app.osint.username_lookup import lookup_username
from app.security.ratelimit import Expensive

router = APIRouter(prefix="/investigate")

_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_AUDIO_BYTES = 100 * 1024 * 1024
# Read uploads in chunks so an oversized body is rejected mid-stream. Reading
# first and checking the length afterwards means the process has already
# allocated whatever the client chose to send.
_CHUNK = 1024 * 1024


async def _read_capped(file: UploadFile, limit: int, label: str) -> bytes:
    buf = bytearray()
    while chunk := await file.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"File too large (max {limit // (1024 * 1024)} MB {label}).")
    if not buf:
        raise HTTPException(400, "Empty file.")
    return bytes(buf)


class PostImageRequest(BaseModel):
    url: str


class ExplainRequest(BaseModel):
    tool: str
    report: dict


@router.post("/image", dependencies=[Expensive])
async def investigate_image(file: UploadFile = File(...), deep_faces: bool = False,
                            session: Session = Depends(get_session)) -> dict:
    data = await _read_capped(file, _MAX_IMAGE_BYTES, "image")
    analysis = analyze_image(data, filename=file.filename or "", deep_faces=deep_faces)
    phash = analysis.get("perceptual_hash")
    reverse = reverse_lookup(phash)
    person = find_person(phash)
    # Faces are matched against the suspect registry here rather than inside
    # analyze_image, which has no DB session. This also strips the raw
    # embeddings before the report is serialised.
    identification = await identify_faces(session, analysis,
                                          filename=file.filename or "")
    return {"analysis": analysis, "reverse_image": reverse, "person": person,
            "identification": identification}


@router.post("/image-from-url", dependencies=[Expensive])
async def investigate_image_from_url(req: PostImageRequest, session: Session = Depends(get_session)) -> dict:
    """Pull the image from a post/image URL and analyze it (no manual upload)."""
    from app.services.audit import log_action
    log_action(session, "osint_image_from_url", req.url)
    report = await analyze_from_url(req.url)
    report["identification"] = await identify_media(session, report, filename=req.url)
    return report

@router.post("/audio", dependencies=[Expensive])
async def investigate_audio(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    """Transcribe an audio/video file with local Whisper.

    Capped and rate-limited: this endpoint buffers the upload, writes it to
    disk and then runs a transformer over it, so it is by far the cheapest way
    to exhaust the server and previously had no size limit at all.
    """
    from app.services.audit import log_action
    from app.osint.audio_analysis import transcribe_audio
    import os
    import tempfile

    content = await _read_capped(file, _MAX_AUDIO_BYTES, "audio")
    log_action(session, "osint_audio_transcribe", file.filename or "",
               {"bytes": len(content)})

    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = transcribe_audio(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return result


@router.get("/post-media/{post_id}", dependencies=[Expensive])
async def investigate_post_media(post_id: str, session: Session = Depends(get_session)) -> dict:
    """Resolve and analyze the media attached to a feed post (or the latest post
    with media when post_id is 'top')."""
    report = await analyze_from_post(post_id)
    report["identification"] = await identify_media(session, report, filename=post_id)
    return report


@router.get("/username", dependencies=[Expensive])
async def investigate_username(u: str, similar: bool = True, deep: bool = True,
                               nsfw: bool = False,
                               session: Session = Depends(get_session)) -> dict:
    """Read the handle's profile on every platform that publishes one, sweep it
    across the Sherlock site manifest, then correlate the lot into one identity.

    `similar=false` skips the variant/user-search pass, which is the expensive
    half — useful when an analyst only wants the direct footprint.
    `deep=false` skips the ~480-site sweep, leaving only the platform reads.
    `nsfw=true` includes the adult sites the manifest flags, which are skipped
    by default.
    """
    from app.services.audit import log_action
    log_action(session, "osint_username_lookup", u,
               {"similar": similar, "deep": deep, "nsfw": nsfw})
    return await lookup_username(u, similar=similar, deep=deep, nsfw=nsfw)


@router.post("/explain", dependencies=[Expensive])
async def investigate_explain(req: ExplainRequest,
                              session: Session = Depends(get_session)) -> dict:
    """LLM commentary on a report this console already produced.

    The report is posted back rather than recomputed: the officer is asking
    about the findings on their screen, and re-running the analysis could
    legitimately return something different, leaving the explanation describing
    a report nobody is looking at.
    """
    from app.services.audit import log_action
    log_action(session, "osint_explain", req.tool)
    return await explain_report(req.tool, req.report)


@router.get("/pr-campaigns", dependencies=[Expensive])
def investigate_pr_campaigns(hours: int = 48, min_accounts: int = 3,
                             session: Session = Depends(get_session)) -> dict:
    from app.services.audit import log_action
    log_action(session, "osint_pr_campaigns", str(hours))
    return detect_pr_campaigns(hours=max(1, min(hours, 168)),
                               min_accounts=max(2, min(min_accounts, 20)))
