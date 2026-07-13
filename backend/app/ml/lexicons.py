"""Weighted multilingual lexicons for the lite NLP engine.

Every entry is (term, weight 0..1). Terms cover Gujarati script, Devanagari,
romanized Hinglish and English so the same signal is caught regardless of how
it is written. Latin-script terms are matched with word boundaries; Indic
terms by substring (no reliable word boundaries after matras).

These lexicons drive: the lite threat classifier, toxicity flags, keyword
severity in the threat score, and the "matched keywords" the analyst sees.
"""

# ── Calls / references to violence ─────────────────────────────────────────
VIOLENCE = [
    # Hindi (Devanagari)
    ("मारो", 1.0), ("मार डालो", 1.0), ("काट दो", 1.0), ("जला दो", 1.0), ("जला देंगे", 1.0),
    ("खत्म कर", 0.95), ("बदला", 0.8), ("हथियार", 0.9), ("हमला", 0.9), ("घेर लो", 0.85),
    ("सबक सिखा", 0.85), ("छोड़ना नहीं", 0.8), ("तोड़ दो", 0.8), ("खून", 0.85), ("लाश", 0.85),
    ("छोड़ेंगे नहीं", 0.85), ("बातों से काम नहीं", 0.7),
    # Gujarati
    ("મારો", 1.0), ("કાપી નાખ", 1.0), ("બાળી નાખ", 1.0), ("ખતમ કર", 0.95), ("બદલો", 0.8),
    ("હુમલો", 0.9), ("હથિયાર", 0.9), ("પાઠ ભણાવ", 0.85), ("ઘેરી લો", 0.85), ("સલામત નહીં", 0.8),
    ("છોડવાના નથી", 0.8), ("તોડી નાખ", 0.8), ("વાતોથી કામ નહીં", 0.7), ("બતાવી દઈએ", 0.6),
    # Romanized (Hinglish)
    ("maaro", 1.0), ("maar do", 1.0), ("kaat do", 1.0), ("jala do", 1.0), ("jala denge", 1.0),
    ("khatam kar", 0.95), ("badla", 0.8), ("hamla", 0.9), ("hathiyar", 0.9), ("sabak sikha", 0.85),
    ("ghera", 0.75), ("chhodna nahi", 0.8), ("tod do", 0.8), ("aukaat dikha", 0.75),
    # English
    ("kill", 1.0), ("attack", 0.9), ("burn", 0.9), ("burn down", 1.0), ("destroy", 0.85),
    ("weapons", 0.9), ("revenge", 0.8), ("teach them a lesson", 0.85), ("wipe out", 0.95),
    ("beat them", 0.85), ("make them pay", 0.85), ("will burn", 0.9), ("not be safe", 0.75),
    ("hunt them", 0.9),
]

# ── Us-vs-them hostility / exclusion (inflammatory) ────────────────────────
HOSTILITY = [
    ("गद्दार", 0.85), ("देशद्रोही", 0.85), ("बाहरी लोग", 0.75), ("बाहर वाले", 0.75),
    ("निकालो", 0.7), ("भगाओ", 0.75), ("बहिष्कार", 0.7), ("इनको यहाँ", 0.6), ("माहौल खराब", 0.6),
    ("शर्म नहीं", 0.55), ("वो लोग", 0.5), ("इन लोगों", 0.5),
    ("ગદ્દાર", 0.85), ("દેશદ્રોહી", 0.85), ("બહારના", 0.75), ("હાંકી કાઢ", 0.8),
    ("બહિષ્કાર", 0.7), ("કોઈ જગ્યા નથી", 0.7), ("બહુ થયું", 0.55), ("એ લોકો", 0.5),
    ("gaddar", 0.85), ("deshdrohi", 0.85), ("bahar wale", 0.75), ("nikalo", 0.7),
    ("bhagao", 0.75), ("boycott", 0.7), ("barbaad kar", 0.65), ("sharam nahi", 0.55),
    ("in logon", 0.5), ("wo log", 0.5),
    ("traitors", 0.85), ("outsiders", 0.7), ("throw them out", 0.8), ("taken over", 0.6),
    ("never forget who", 0.6), ("wake up before", 0.55), ("not welcome", 0.65),
    ("real locals", 0.5), ("living among us", 0.6),
]

# ── Misinformation markers (fake-news style framing) ───────────────────────
FAKE_MARKERS = [
    ("मीडिया नहीं दिखाएगा", 0.9), ("फॉरवर्ड करो", 0.8), ("वायरल", 0.6), ("साज़िश", 0.7),
    ("षड्यंत्र", 0.7), ("सच्चाई", 0.55), ("ब्रेकिंग", 0.5), ("जितना हो सके", 0.6),
    ("डिलीट होने से पहले", 0.9), ("बच्चा चोर", 0.85), ("अफवाह", 0.6), ("जहर मिलाया", 0.85),
    ("મીડિયા નહીં બતાવે", 0.9), ("ફોરવર્ડ કરો", 0.8), ("વાયરલ", 0.6), ("ષડયંત્ર", 0.7),
    ("સાચું નહીં કહે", 0.7), ("છુપાવે છે", 0.7), ("બધાને મોકલો", 0.75), ("ગાયબ થઈ", 0.5),
    ("media nahi dikhayega", 0.9), ("forward karo", 0.8), ("viral kar do", 0.8),
    ("sazish", 0.7), ("sach jo media", 0.85), ("delete hone se pehle", 0.9),
    ("proof delete", 0.8), ("bacha chor", 0.85), ("share karo sab", 0.7),
    ("share before deleted", 0.9), ("they don't want you to know", 0.85), ("exposed", 0.55),
    ("leaked document", 0.6), ("secret plan", 0.7), ("government hiding", 0.8),
    ("doctors won't tell", 0.8), ("wake up people", 0.55), ("100% true", 0.7),
    ("conspiracy", 0.6),
]

# ── Mobilization / call-to-action ───────────────────────────────────────────
CALL_TO_ACTION = [
    ("इकट्ठा हो", 0.9), ("पहुंच जाओ", 0.8), ("लेकर आओ", 0.8), ("तैयार रहो", 0.7), ("चलो सब", 0.7),
    ("ભેગા થાઓ", 0.9), ("પહોંચી જાઓ", 0.8), ("તૈયાર રહો", 0.7), ("લઈને આવો", 0.8),
    ("aa jao", 0.75), ("pahunch jao", 0.8), ("ikattha", 0.9), ("lekar aao", 0.8),
    ("taiyar raho", 0.7), ("sab log aao", 0.8),
    ("gather at", 0.9), ("bring everyone", 0.85), ("be ready", 0.6), ("join us at", 0.8),
    ("time to act", 0.75), ("bring your boys", 0.95),
]

# ── References to office-holders (threat-to-official signal) ───────────────
OFFICIALS = [
    ("मंत्री", 0.6), ("विधायक", 0.6), ("नेता", 0.5), ("अफसर", 0.5), ("कमिश्नर", 0.6),
    ("મંત્રી", 0.6), ("ધારાસભ્ય", 0.6), ("નેતા", 0.5), ("કમિશનર", 0.6),
    ("mantri", 0.6), ("vidhayak", 0.6), ("neta", 0.5),
    ("mla", 0.6), ("minister", 0.6), ("mayor", 0.6), ("commissioner", 0.6),
    ("collector", 0.55), ("sarpanch", 0.55), ("officer", 0.45),
]

# ── Abusive / degrading language (toxicity) ─────────────────────────────────
ABUSE = [
    ("नीच", 0.7), ("कमीना", 0.75), ("कुत्ते", 0.7), ("गंदे लोग", 0.6), ("घटिया", 0.6),
    ("नालायक", 0.6), ("बेशर्म", 0.55),
    ("નીચ", 0.7), ("કમીના", 0.75), ("કૂતરા", 0.7), ("ગંદા લોકો", 0.6), ("બેશરમ", 0.55),
    ("kamina", 0.75), ("kutte", 0.7), ("ghatiya", 0.6), ("nalayak", 0.6), ("besharam", 0.55),
    ("gande log", 0.6), ("aukaat", 0.6),
    ("scum", 0.8), ("vermin", 0.9), ("filthy", 0.7), ("shameless", 0.55), ("disgusting people", 0.6),
]

# ── Sentiment valence ───────────────────────────────────────────────────────
# Expanded VADER-style (cjhutto/vaderSentiment): a wide valence lexicon is what
# makes the rule engine work; entries span Devanagari, Gujarati script,
# romanized Hinglish/Gujlish and English.
POSITIVE = [
    # Hindi (Devanagari)
    ("सुंदर", 0.7), ("शानदार", 0.8), ("बधाई", 0.8), ("लाजवाब", 0.8), ("रौनक", 0.6), ("जरूर जाएं", 0.5),
    ("अच्छा", 0.6), ("अच्छी", 0.6), ("बढ़िया", 0.7), ("प्यार", 0.7), ("खुशी", 0.7), ("खुश", 0.7),
    ("मज़ा", 0.7), ("धन्यवाद", 0.7), ("शुक्रिया", 0.7), ("कमाल", 0.7), ("जबरदस्त", 0.8),
    ("स्वादिष्ट", 0.7), ("शुभ", 0.6), ("सफल", 0.7), ("जीत", 0.7), ("गर्व", 0.7), ("उम्मीद", 0.5),
    # Gujarati script
    ("સુંદર", 0.7), ("સરસ", 0.7), ("ધન્યવાદ", 0.8), ("મજા", 0.7), ("સારી", 0.6), ("ઝડપથી", 0.4),
    ("સારું", 0.6), ("સરું", 0.6), ("ખુશ", 0.7), ("ખુશી", 0.7), ("આનંદ", 0.7), ("અભિનંદન", 0.8),
    ("પ્રેમ", 0.7), ("જોરદાર", 0.8), ("કમાલ", 0.7), ("સ્વાદિષ્ટ", 0.7), ("જીત", 0.7), ("ગર્વ", 0.7),
    # Romanized Hinglish / Gujlish
    ("badhiya", 0.7), ("mast", 0.7), ("maja", 0.7), ("paisa vasool", 0.8), ("shandar", 0.8),
    ("accha", 0.6), ("acha", 0.6), ("achha", 0.6), ("sahi", 0.5), ("zabardast", 0.8),
    ("kamaal", 0.7), ("dhamaal", 0.7), ("khush", 0.7), ("khushi", 0.7), ("pyaar", 0.7),
    ("shukriya", 0.7), ("dhanyavad", 0.7), ("jeet", 0.7), ("garv", 0.7), ("saru", 0.6),
    ("saras", 0.7), ("jordar", 0.8), ("anand", 0.7), ("abhinandan", 0.8), ("jakkas", 0.8),
    ("jhakaas", 0.8), ("op", 0.5), ("swadisht", 0.7), ("vadhare saru", 0.7),
    # English
    ("beautiful", 0.7), ("great", 0.6), ("love", 0.7), ("amazing", 0.8), ("wonderful", 0.8),
    ("celebration", 0.6), ("congrats", 0.8), ("excited", 0.6), ("delicious", 0.7),
    ("good", 0.5), ("nice", 0.5), ("awesome", 0.8), ("excellent", 0.8), ("fantastic", 0.8),
    ("happy", 0.7), ("thanks", 0.6), ("thank you", 0.7), ("best", 0.7), ("perfect", 0.8),
    ("win", 0.6), ("proud", 0.7), ("super", 0.6), ("brilliant", 0.8), ("helpful", 0.6),
    ("enjoyed", 0.7), ("blessed", 0.7), ("favorite", 0.6), ("favourite", 0.6),
]

NEGATIVE = [
    # Hindi (Devanagari)
    ("डर", 0.6), ("खतरा", 0.7), ("सावधान", 0.5), ("बर्बाद", 0.7), ("नफरत", 0.8), ("गुस्सा", 0.6),
    ("बुरा", 0.6), ("बुरी", 0.6), ("गंदा", 0.6), ("बकवास", 0.7), ("घटिया", 0.8), ("झूठ", 0.6),
    ("धोखा", 0.7), ("शर्मनाक", 0.7), ("दुख", 0.6), ("दर्द", 0.6), ("रोना", 0.5), ("परेशान", 0.6),
    ("नाराज", 0.6), ("विफल", 0.6), ("हार", 0.5), ("भ्रष्ट", 0.7), ("घोटाला", 0.7),
    # Gujarati script
    ("ડર", 0.6), ("ખતરો", 0.7), ("સાવધાન", 0.5), ("બરબાદ", 0.7), ("નફરત", 0.8),
    ("ખરાબ", 0.6), ("ગંદું", 0.6), ("બકવાસ", 0.7), ("નબળી", 0.5), ("નબળું", 0.5),
    ("જૂઠ", 0.6), ("દગો", 0.7), ("શરમજનક", 0.7), ("દુઃખ", 0.6), ("દર્દ", 0.6),
    ("પરેશાન", 0.6), ("નિરાશ", 0.6), ("ભ્રષ્ટ", 0.7), ("કૌભાંડ", 0.7),
    # Romanized Hinglish / Gujlish
    ("darr", 0.6), ("khatra", 0.7), ("nafrat", 0.8), ("gussa", 0.6), ("barbaad", 0.7),
    ("bura", 0.6), ("buri", 0.6), ("ganda", 0.6), ("bakwas", 0.7), ("bakwaas", 0.7),
    ("ghatiya", 0.8), ("bekar", 0.6), ("bekaar", 0.6), ("jhooth", 0.6), ("dhoka", 0.7),
    ("sharamnak", 0.7), ("dukh", 0.6), ("dard", 0.6), ("pareshan", 0.6), ("naraz", 0.6),
    ("kharab", 0.6), ("nabli", 0.5), ("faltu", 0.6), ("ghotala", 0.7), ("bhrasht", 0.7),
    ("nakli", 0.6), ("dagabaz", 0.7), ("kangal", 0.6),
    # English
    ("fear", 0.6), ("danger", 0.7), ("hate", 0.8), ("angry", 0.6), ("ruined", 0.7),
    ("terrible", 0.7), ("suffering", 0.6), ("bad", 0.5), ("worst", 0.8), ("awful", 0.8),
    ("horrible", 0.8), ("disgusting", 0.8), ("pathetic", 0.7), ("useless", 0.7),
    ("waste", 0.6), ("fraud", 0.7), ("scam", 0.7), ("fake", 0.6), ("corrupt", 0.7),
    ("sad", 0.6), ("cry", 0.5), ("pain", 0.6), ("failed", 0.6), ("failure", 0.7),
    ("disappointed", 0.7), ("disappointing", 0.7), ("cheap", 0.4), ("dirty", 0.6),
    ("shame", 0.6), ("sucks", 0.7), ("broken", 0.5), ("poor", 0.5),
]

POSITIVE_EMOJI = set("😍❤️🎉😊🙏✨🏏☕🎊💚")
NEGATIVE_EMOJI = set("😡🤬💀🔥⚠️😠")
