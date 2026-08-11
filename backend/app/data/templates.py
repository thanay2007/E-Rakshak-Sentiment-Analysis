# -*- coding: utf-8 -*-
"""SENTINEL synthetic multilingual corpus.

Template library for the simulated ingestion mode, the seed history and the
labeled train/test datasets. Every template carries:
  lang   : hi (Hindi/Devanagari) | gu (Gujarati script) | hing (romanized) | en
  text   : template with {city} {group} {place} {time} {official} slots
  gloss  : English translation shown to the analyst
  tags   : hashtag pool
All hostile content is SYNTHETIC, uses deliberately generic targets ("those
people", "outsiders") and fictional office-holders. It exists solely to
train/demo the analysis system.

**Themes are not labels.** The four keys of TEMPLATES — everyday, hostile,
mobilization, rumor — describe what a template is ABOUT, so the simulated
stream has a realistic mix of subject matter. They are not what the system
predicts: the only tag a post receives is its sentiment (positive, negative,
neutral), and `THEME_TONE` below maps each theme to the ground-truth sentiment
used for the live accuracy KPI. Templates in the `everyday` theme carry their
own `tone`, because "the food festival was amazing" and "traffic diversion near
the metro works" are both everyday posts and only one of them is positive.
"""

CITIES = {
    "Ahmedabad": (23.0225, 72.5714),
    "Surat": (21.1702, 72.8311),
    "Vadodara": (22.3072, 73.1812),
    "Rajkot": (22.3039, 70.8022),
    "Gandhinagar": (23.2156, 72.6369),
    "Bhavnagar": (21.7645, 72.1519),
    "Jamnagar": (22.4707, 70.0577),
    "Junagadh": (21.5222, 70.4579),
}

PLACES = ["Station Chowk", "Old Market", "Bus Stand", "River Bridge", "College Gate", "Clock Tower", "Sardar Circle"]

OFFICIALS = ["MLA Kiran Vaghela", "Minister R. Solanki", "Mayor D. Chauhan", "Commissioner A. Rathod", "Collector S. Mehta"]

GROUPS = {
    "hi": ["बाहर के लोग", "वो लोग", "गद्दार लोग"],
    "gu": ["બહારના લોકો", "એ લોકો", "ગદ્દારો"],
    "hing": ["bahar wale", "wo log", "gaddar log"],
    "en": ["outsiders", "those people", "the traitors"],
}

TIMES = {
    "hi": ["आज रात 9 बजे", "कल शाम", "रविवार दोपहर"],
    "gu": ["આજે રાત્રે 9 વાગ્યે", "કાલે સાંજે", "રવિવારે બપોરે"],
    "hing": ["aaj raat 9 baje", "kal shaam", "sunday dopahar"],
    "en": ["tonight 9pm", "tomorrow evening", "Sunday afternoon"],
}

TEMPLATES = {
    # ───────────────────── EVERYDAY CIVIC / SOCIAL LIFE ──────────────────
    "everyday": [
        {"lang": "hi", "text": "{city} में आज बारिश के बाद मौसम बहुत सुहाना है ☕", "gloss": "The weather in {city} is lovely after today's rain ☕", "tags": ["Monsoon", "{city}"], "tone": "positive"},
        {"lang": "hi", "text": "{city} के नए फूड फेस्टिवल में जरूर जाएं, खाना लाजवाब है 😍", "gloss": "Do visit the new food festival in {city}, the food is amazing 😍", "tags": ["FoodFestival", "{city}"], "tone": "positive"},
        {"lang": "hi", "text": "नवरात्रि की तैयारियां शुरू, {city} के बाजारों में रौनक है 🎉", "gloss": "Navratri preparations have begun, {city}'s markets are buzzing 🎉", "tags": ["Navratri", "Garba"], "tone": "positive"},
        {"lang": "hi", "text": "{place} के पास मेट्रो का काम चल रहा है, ट्रैफिक से बचकर निकलें", "gloss": "Metro work is underway near {place}, avoid the traffic", "tags": ["Traffic", "{city}"], "tone": "neutral"},
        {"lang": "gu", "text": "{city} માં નવી મેટ્રો લાઇનનું કામ ઝડપથી ચાલી રહ્યું છે, સરસ પ્રગતિ", "gloss": "Work on the new metro line in {city} is progressing fast, great progress", "tags": ["Metro", "{city}"], "tone": "positive"},
        {"lang": "gu", "text": "આજે {city} માં ખૂબ ટ્રાફિક છે, વહેલા નીકળજો 🙏", "gloss": "Heavy traffic in {city} today, leave early 🙏", "tags": ["Traffic"], "tone": "neutral"},
        {"lang": "gu", "text": "{city} ના રિવરફ્રન્ટ પર સાંજ ખૂબ સુંદર હતી ✨", "gloss": "The evening at {city}'s riverfront was beautiful ✨", "tags": ["Riverfront", "{city}"], "tone": "positive"},
        {"lang": "gu", "text": "ગરબા ક્લાસ શરૂ થઈ ગયા છે, આ વર્ષે માજા આવશે 🎊", "gloss": "Garba classes have started, this year will be fun 🎊", "tags": ["Garba", "Navratri"], "tone": "positive"},
        {"lang": "hing", "text": "Aaj ka match dekha kya bhai? Kya batting thi! 🏏", "gloss": "Did you watch today's match, brother? What batting! 🏏", "tags": ["Cricket"], "tone": "positive"},
        {"lang": "hing", "text": "Yaar {city} ki garba night full paisa vasool thi 🎉", "gloss": "The garba night in {city} was totally worth it 🎉", "tags": ["Garba", "{city}"], "tone": "positive"},
        {"lang": "hing", "text": "Monday blues... chai aur kaam, bas yahi life hai ☕", "gloss": "Monday blues... tea and work, that's life ☕", "tags": ["MondayMotivation"], "tone": "neutral"},
        {"lang": "hing", "text": "{city} me naya cafe khula hai {place} ke paas, coffee badhiya hai", "gloss": "A new cafe opened in {city} near {place}, the coffee is great", "tags": ["Cafe", "{city}"], "tone": "positive"},
        {"lang": "en", "text": "Beautiful sunset at the {city} riverfront this evening. This city never disappoints.", "gloss": "Beautiful sunset at the {city} riverfront this evening. This city never disappoints.", "tags": ["{city}", "Sunset"], "tone": "positive"},
        {"lang": "en", "text": "New IT park announced in {city} — expected to create 5,000 jobs. Great news for the region!", "gloss": "New IT park announced in {city} — expected to create 5,000 jobs. Great news for the region!", "tags": ["Jobs", "{city}"], "tone": "positive"},
        {"lang": "en", "text": "Traffic diversion near {place} due to metro construction. Plan your commute accordingly.", "gloss": "Traffic diversion near {place} due to metro construction. Plan your commute accordingly.", "tags": ["Traffic", "CityUpdates"], "tone": "neutral"},
    ],
    # ──────────────────── HOSTILE / EXCLUSIONARY RHETORIC ────────────────
    "hostile": [
        {"lang": "hi", "text": "ये {group} हमारे {city} का माहौल खराब कर रहे हैं। इनको यहाँ से निकालो! अब बर्दाश्त नहीं होगा", "gloss": "These {group} are ruining the atmosphere of our {city}. Throw them out! We won't tolerate this anymore", "tags": ["WakeUp{city}"]},
        {"lang": "hi", "text": "जो लोग हमारे त्योहार का विरोध करते हैं वो देशद्रोही हैं। इनका पूरा बहिष्कार करो", "gloss": "Those who oppose our festival are traitors. Boycott them completely", "tags": ["Boycott"]},
        {"lang": "hi", "text": "{city} में {group} की दुकानों से कुछ मत खरीदो। ये लोग हमारे खिलाफ हैं", "gloss": "Don't buy anything from {group}'s shops in {city}. These people are against us", "tags": ["Boycott", "{city}"]},
        {"lang": "gu", "text": "આ {group} ને આપણા વિસ્તારમાં કોઈ જગ્યા નથી. બહુ થયું હવે!", "gloss": "These {group} have no place in our area. Enough is enough!", "tags": ["SaveOurCity"]},
        {"lang": "gu", "text": "{group} ની દુકાનેથી કંઈ ખરીદશો નહીં. આ લોકો આપણા વિરોધી છે, બહિષ્કાર કરો", "gloss": "Don't buy anything from {group}'s shops. These people are our opponents, boycott them", "tags": ["Boycott"]},
        {"lang": "gu", "text": "જે લોકો {city} ની સંસ્કૃતિનું અપમાન કરે છે એ ગદ્દારો છે. યાદ રાખજો", "gloss": "Those who insult {city}'s culture are traitors. Remember them", "tags": ["{city}"]},
        {"lang": "hing", "text": "In {group} ki wajah se hamara area barbaad ho gaya hai. Sharam nahi aati inko. Nikalo sabko", "gloss": "Because of these {group} our area is ruined. They have no shame. Throw them all out", "tags": ["WakeUp"]},
        {"lang": "hing", "text": "Ye {group} hamesha drama karte hain hamare festivals pe. Inka boycott karo sab log! #Boycott", "gloss": "These {group} always create drama during our festivals. Everyone boycott them! #Boycott", "tags": ["Boycott"]},
        {"lang": "en", "text": "Our {city} is being taken over by {group}. Real locals must wake up before it's too late.", "gloss": "Our {city} is being taken over by {group}. Real locals must wake up before it's too late.", "tags": ["WakeUp{city}"]},
        {"lang": "en", "text": "These traitors living among us celebrate when {city} suffers. Never forget who they are.", "gloss": "These traitors living among us celebrate when {city} suffers. Never forget who they are.", "tags": ["NeverForget"]},
    ],
    # ─────────────────────── MOBILIZATION / THREATS ──────────────────────
    "mobilization": [
        {"lang": "hi", "text": "{time} {place} पर इकट्ठा हो जाओ। इन {group} को सबक सिखाना है। सब अपने लड़के लेकर आओ", "gloss": "Gather at {place} {time}. We must teach these {group} a lesson. Everyone bring your boys", "tags": ["FinalWarning"]},
        {"lang": "hi", "text": "{official} ने जो किया उसके बाद उसे छोड़ना नहीं है। उसका घर सबको पता है", "gloss": "After what {official} did, we must not spare them. Everyone knows where they live", "tags": []},
        {"lang": "hi", "text": "अगर पुलिस {group} के खिलाफ कुछ नहीं करेगी तो हम करेंगे। बदला लेकर रहेंगे", "gloss": "If the police won't act against {group}, we will. We will take revenge", "tags": ["{city}Rising"]},
        {"lang": "gu", "text": "હવે વાતોથી કામ નહીં થાય. {time} {place} પર ભેગા થાઓ, બતાવી દઈએ આપણે શું કરી શકીએ", "gloss": "Talking won't work anymore. Gather at {place} {time}, let's show what we can do", "tags": ["FinalWarning"]},
        {"lang": "gu", "text": "એ લોકોની દુકાનો {time} પછી સલામત નહીં રહે. બધા તૈયાર રહો", "gloss": "Their shops won't be safe after {time}. Everyone be ready", "tags": []},
        {"lang": "gu", "text": "{official} ને પાઠ ભણાવવો પડશે. બહુ થયું, હવે બદલો લેવાનો સમય છે", "gloss": "{official} must be taught a lesson. Enough — now it's time for revenge", "tags": []},
        {"lang": "hing", "text": "Bahut ho gaya bhai. {time} sab {place} pe aa jao, in {group} ko sabak sikhana hai. Share karo sab groups me", "gloss": "Enough is enough, brother. Everyone come to {place} {time}, we must teach these {group} a lesson. Share in all groups", "tags": ["FinalWarning"]},
        {"lang": "hing", "text": "{official} ko uski aukaat dikhani hogi. Agli baar public me dikha to samajh lo kya hoga", "gloss": "{official} must be shown their place. If they appear in public again, you know what will happen", "tags": []},
        {"lang": "en", "text": "Words are done. Time to make {group} pay. {place}, {time}. Bring everyone you trust.", "gloss": "Words are done. Time to make {group} pay. {place}, {time}. Bring everyone you trust.", "tags": ["FinalWarning"]},
        {"lang": "en", "text": "If the police won't act against {group}, we will. {city} will burn before we back down.", "gloss": "If the police won't act against {group}, we will. {city} will burn before we back down.", "tags": ["{city}Rising"]},
    ],
    # ──────────────────── VIRAL RUMOR / FORWARD-BAIT ─────────────────────
    "rumor": [
        {"lang": "hi", "text": "ब्रेकिंग: {city} के पानी में जहर मिलाया गया है! मीडिया नहीं दिखाएगा। जितना हो सके फॉरवर्ड करो!", "gloss": "BREAKING: Poison has been mixed into {city}'s water supply! The media won't show this. Forward as much as you can!", "tags": ["Breaking", "Viral"]},
        {"lang": "hi", "text": "सावधान! {city} में बच्चा चोर गिरोह घूम रहा है। अनजान गाड़ी दिखे तो तुरंत सबको बताओ", "gloss": "Warning! A child-kidnapper gang is roaming {city}. If you see an unknown vehicle, alert everyone immediately", "tags": ["Alert", "{city}"]},
        {"lang": "hi", "text": "सच्चाई जो कोई नहीं दिखाएगा: {official} ने {city} का पैसा विदेश भेजा है। डिलीट होने से पहले शेयर करो", "gloss": "The truth no one will show: {official} sent {city}'s money abroad. Share before it gets deleted", "tags": ["Exposed"]},
        {"lang": "gu", "text": "વાયરલ: {city} માં રાત્રે ATM માંથી પૈસા ગાયબ થઈ રહ્યા છે. બેંક વાળા છુપાવે છે. બધાને મોકલો!", "gloss": "VIRAL: Money is disappearing from ATMs in {city} at night. The banks are hiding it. Send to everyone!", "tags": ["Viral"]},
        {"lang": "gu", "text": "ડોક્ટરો છુપાવે છે: આ દેશી ઉપાયથી કેન્સર 7 દિવસમાં મટે છે. ફોરવર્ડ કરો, કોઈનો જીવ બચશે", "gloss": "Doctors are hiding it: this home remedy cures cancer in 7 days. Forward it, it could save a life", "tags": ["Health", "Viral"]},
        {"lang": "gu", "text": "સાચું નહીં કહે કોઈ: {city} ના નવા ટાવરથી પક્ષીઓ મરી રહ્યા છે અને બીમારીઓ ફેલાય છે. ષડયંત્ર છે", "gloss": "No one will tell the truth: birds are dying from {city}'s new towers and diseases are spreading. It's a conspiracy", "tags": ["Conspiracy"]},
        {"lang": "hing", "text": "Sach jo media nahi dikhayega: {official} ne {city} ka paisa videsh bheja hai. Proof delete hone se pehle share karo!", "gloss": "The truth the media won't show: {official} sent {city}'s money abroad. Share before the proof is deleted!", "tags": ["Exposed", "Viral"]},
        {"lang": "hing", "text": "EVM machines {city} me raat ko badli gayi. Video dekho jaldi, har jagah se delete ho raha hai! Forward karo", "gloss": "EVM machines were swapped at night in {city}. Watch the video quickly, it's being deleted everywhere! Forward it", "tags": ["EVM", "Breaking"]},
        {"lang": "en", "text": "EXPOSED: {group} are secretly planning to take over the {city} municipal council. Leaked document shows everything. Share before it's deleted!", "gloss": "EXPOSED: {group} are secretly planning to take over the {city} municipal council. Leaked document shows everything. Share before it's deleted!", "tags": ["Exposed", "Leaked"]},
        {"lang": "en", "text": "Government hiding it: the new phone towers in {city} are causing bird deaths and cancer. Wake up people! 100% true.", "gloss": "Government hiding it: the new phone towers in {city} are causing bird deaths and cancer. Wake up people! 100% true.", "tags": ["WakeUp", "Truth"]},
    ],
}

# Ground-truth sentiment per theme, for the live accuracy KPI on /api/stats.
# `everyday` is None because those templates carry their own `tone` — the theme
# alone does not determine whether a post about city life is positive or merely
# informational.
THEME_TONE = {
    "everyday": None,
    "hostile": "negative",
    "mobilization": "negative",
    "rumor": "negative",
}

LANG_NAMES = {"hi": "Hindi", "gu": "Gujarati", "hing": "Hinglish", "en": "English"}
