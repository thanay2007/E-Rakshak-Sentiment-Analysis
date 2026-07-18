"""Gujlish/Slang preprocessor for the ML pipeline."""
import re

# A mock database of local gang/riot slang mapped to standard English/Hindi
# In production, this would be a dynamic DB table updated by analysts.
SLANG_DICT = {
    r"\bmms\b": "scandal video",
    r"\blaude\b": "idiot", # (abusive)
    r"\bgang\b": "group",
    r"\bpel denge\b": "will beat you up",
    r"\bkaat denge\b": "will cut/kill",
    r"\bmara mari\b": "violent clash",
    r"\bsystem phaad\b": "destroy the system",
    r"\bpatthar\b": "stones",
    r"\btod fod\b": "vandalism",
    r"\bjala do\b": "burn it",
    r"\bkhatam kar\b": "finish them",
}

def translate_slang(text: str) -> str:
    """Pre-processes text by translating local Gujlish/street slang 
    into standard terms that the primary NLP model can understand."""
    translated = text.lower()
    for pattern, replacement in SLANG_DICT.items():
        translated = re.sub(pattern, replacement, translated)
    
    # Preserve original casing roughly where possible or just return lowercase
    # since BERT/RoBERTa handles lowercase well.
    return translated
