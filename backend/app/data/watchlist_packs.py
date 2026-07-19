# -*- coding: utf-8 -*-
"""Curated watchlist preset packs — one-click monitoring playbooks.

Each pack is a themed set of terms an intelligence analyst would track for
that threat type, across every script the pipeline reads (English, Hindi
Devanagari, Gujarati script, romanized Hinglish/Gujlish). Packs are applied
from the Watchlist page (POST /api/watchlist/presets/{slug}); duplicates
already on the watchlist are skipped, so re-applying is safe.

Entry shape: (kind, value, note, priority).
"""

PACKS: dict[str, dict] = {
    "communal-tension": {
        "title": "Communal Tension",
        "description": "Phrases that historically precede communal flashpoints — rumor triggers, framing language, and gathering calls in all scripts.",
        "items": [
            ("keyword", "बच्चा चोर", "child-kidnapper rumor trigger (Hindi)", "critical"),
            ("keyword", "bacha chor", "child-kidnapper rumor (Hinglish)", "critical"),
            ("keyword", "बच्चा चोरी गिरोह", "kidnapping-gang rumor phrase (Hindi)", "high"),
            ("keyword", "धर्म के दुश्मन", "communal framing phrase (Hindi)", "high"),
            ("keyword", "dharm ke dushman", "communal framing (Hinglish)", "high"),
            ("keyword", "उनके इलाके", "us-vs-them area framing (Hindi)", "medium"),
            ("keyword", "કોમી રમખાણ", "communal riot (Gujarati)", "critical"),
            ("keyword", "komi ramkhan", "communal riot (Gujlish)", "critical"),
            ("keyword", "અફવા", "rumor (Gujarati)", "medium"),
            ("keyword", "afwa", "rumor (Gujlish/Hinglish)", "medium"),
            ("keyword", "मंदिर पर हमला", "attack-on-temple rumor pattern (Hindi)", "critical"),
            ("keyword", "मस्जिद पर हमला", "attack-on-mosque rumor pattern (Hindi)", "critical"),
            ("hashtag", "SaveOurCommunity", "communal mobilization hashtag pattern", "high"),
        ],
    },
    "mobilization": {
        "title": "Mobilization & Incitement",
        "description": "Calls to gather, arm, block roads or 'teach a lesson' — the operational language of street mobilization.",
        "items": [
            ("keyword", "sabak sikhana", "teach-a-lesson mobilization (Hinglish)", "critical"),
            ("keyword", "सबक सिखाना", "teach-a-lesson mobilization (Hindi)", "critical"),
            ("keyword", "ભેગા થાઓ", "gathering call (Gujarati)", "critical"),
            ("keyword", "bhega thao", "gathering call (Gujlish)", "critical"),
            ("keyword", "इकट्ठा हो जाओ", "gathering call (Hindi)", "critical"),
            ("keyword", "ikattha ho jao", "gathering call (Hinglish)", "critical"),
            ("keyword", "रास्ता रोको", "road-block call (Hindi)", "high"),
            ("keyword", "rasta roko", "road-block call (Hinglish)", "high"),
            ("keyword", "chakka jam", "traffic-blockade call", "high"),
            ("keyword", "हथियार उठाओ", "call to arms (Hindi)", "critical"),
            ("keyword", "hathiyar uthao", "call to arms (Hinglish)", "critical"),
            ("hashtag", "FinalWarning", "ultimatum-style mobilization hashtag", "critical"),
            ("hashtag", "Bandh", "shutdown call — spikes before street action", "high"),
            ("keyword", "आर पार की लड़ाई", "decisive-battle framing (Hindi)", "high"),
        ],
    },
    "misinformation": {
        "title": "Misinformation & Fake News",
        "description": "Formats and phrases that carry viral fake news — forwarded-as-received chains, miracle cures, fabricated advisories.",
        "items": [
            ("keyword", "forwarded as received", "chain-message disclaimer — classic misinfo marker", "medium"),
            ("keyword", "सच्चाई जान लो", "know-the-truth clickbait (Hindi)", "medium"),
            ("keyword", "sachai jaan lo", "know-the-truth clickbait (Hinglish)", "medium"),
            ("keyword", "मीडिया नहीं दिखाएगा", "media-won't-show-you framing (Hindi)", "high"),
            ("keyword", "media nahi dikhayega", "media-won't-show-you framing (Hinglish)", "high"),
            ("keyword", "વાયરલ સત્ય", "viral truth claim (Gujarati)", "medium"),
            ("keyword", "100% सच", "certainty-claim marker (Hindi)", "medium"),
            ("keyword", "वैज्ञानिकों ने माना", "fake scientists-confirm attribution (Hindi)", "medium"),
            ("keyword", "government banned", "fabricated ban/advisory pattern", "medium"),
            ("keyword", "सरकारी आदेश", "fake government-order chain (Hindi)", "high"),
            ("keyword", "sarkari aadesh", "fake government-order chain (Hinglish)", "high"),
            ("hashtag", "Exposed", "exposé-style misinfo hashtag", "low"),
        ],
    },
    "cyber-fraud": {
        "title": "Cyber Fraud & Scams",
        "description": "Bank-fraud panic, lottery/job scams and UPI phishing language that targets Gujarat's trading communities.",
        "items": [
            ("keyword", "bank collapse", "bank-run rumor — market panic trigger", "critical"),
            ("keyword", "बैंक डूब गया", "bank-collapse rumor (Hindi)", "critical"),
            ("keyword", "bank doob gaya", "bank-collapse rumor (Hinglish)", "critical"),
            ("keyword", "पैसा निकाल लो", "withdraw-your-money panic call (Hindi)", "critical"),
            ("keyword", "paisa nikal lo", "withdraw-your-money panic call (Hinglish)", "critical"),
            ("keyword", "KYC update", "KYC-phishing scam hook", "high"),
            ("keyword", "lottery jeeta", "lottery scam hook (Hinglish)", "medium"),
            ("keyword", "OTP share", "OTP-harvesting scam marker", "high"),
            ("keyword", "work from home earn", "job-scam hook", "medium"),
            ("keyword", "લોટરી લાગી", "lottery scam (Gujarati)", "medium"),
            ("keyword", "investment double", "double-your-money scam hook", "high"),
        ],
    },
    "protest-unrest": {
        "title": "Protest & Civil Unrest",
        "description": "Strike calls, protest logistics and escalation language around planned demonstrations.",
        "items": [
            ("keyword", "हड़ताल", "strike call (Hindi)", "high"),
            ("keyword", "hartal", "strike call (romanized)", "high"),
            ("keyword", "आंदोलन", "agitation/movement (Hindi)", "medium"),
            ("keyword", "andolan", "agitation/movement (Hinglish)", "medium"),
            ("keyword", "ઘેરાવ", "gherao/encirclement protest (Gujarati)", "high"),
            ("keyword", "gherav", "gherao/encirclement protest (Gujlish)", "high"),
            ("keyword", "पुलिस के खिलाफ", "anti-police framing (Hindi)", "high"),
            ("keyword", "police ke khilaf", "anti-police framing (Hinglish)", "high"),
            ("keyword", "morcha nikalenge", "march announcement (Hinglish)", "high"),
            ("hashtag", "Boycott", "economic-exclusion campaigns", "medium"),
            ("hashtag", "Justice", "grievance-rally hashtag family", "low"),
        ],
    },
}


def pack_summaries() -> list[dict]:
    return [{"slug": slug, "title": p["title"], "description": p["description"],
             "count": len(p["items"])} for slug, p in PACKS.items()]
