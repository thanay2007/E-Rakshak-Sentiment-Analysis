# -*- coding: utf-8 -*-
"""TF-IDF + LinearSVC sentiment baseline (the classical approach used by the
reference repos yasaswini-0411/AI-Powered-Social-Media-Sentiment-Analysis and
gauthamvenkatesh/Social-Media-Sentiment-Analysis, where Linear SVM beat
Naive Bayes / Logistic Regression / Random Forest).

Trains on the SAME corpus as the MuRIL fine-tune so the two are directly
comparable — the delta is the evidence that the transformer earns its cost.
Char n-grams (2-5) are essential here: they are what lets a linear model cope
with Hinglish/Gujlish spelling variation ("bahut/bhut/bohot").

Usage (from backend/):  python -m app.ml.train_baseline
Writes ml/baseline_report.json (overall + per-language, same shape as the
transformer's sentiment_eval_report.json).
"""
import json
from collections import defaultdict

from app.config import settings
from app.ml.corpus import load_corpus

# Multilingual stop-words (idea from zdmc23/sentiment-analysis-arabic, which
# strips a 750-word Arabic list before training): function words carry no
# valence but dominate raw counts. Word n-grams skip them; char n-grams keep
# full text so code-mixed morphology still comes through.
STOPWORDS = [
    # English
    "the", "a", "an", "and", "or", "but", "if", "of", "at", "by", "for", "with",
    "to", "from", "in", "on", "is", "are", "was", "were", "be", "been", "it",
    "this", "that", "i", "you", "he", "she", "we", "they", "my", "your", "his",
    "her", "our", "their", "as", "so", "do", "does", "did", "have", "has", "had",
    # romanized Hindi/Gujarati function words
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "par", "aur", "ya",
    "toh", "hi", "bhi", "woh", "yeh", "hum", "tum", "aap", "ne", "chhe", "che",
    "ane", "pan", "thi", "nu", "na", "ma", "te", "aa", "ek",
    # Devanagari
    "है", "हैं", "का", "की", "के", "को", "से", "में", "पर", "और", "या", "तो",
    "ही", "भी", "वह", "यह", "हम", "तुम", "आप", "ने", "एक", "कि",
    # Gujarati script
    "છે", "અને", "પણ", "થી", "નું", "ના", "મા", "તે", "આ", "એક", "કે", "જ",
]


def main() -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.pipeline import FeatureUnion
    from sklearn.svm import LinearSVC

    print("Building corpus from the raw dataset files ...")
    train, test = load_corpus()

    X_tr, y_tr = [r["text"] for r in train], [r["label"] for r in train]
    X_te, y_te = [r["text"] for r in test], [r["label"] for r in test]

    vec = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), max_features=120_000,
                                 sublinear_tf=True, stop_words=STOPWORDS)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                 max_features=200_000, sublinear_tf=True)),
    ])
    print(f"Vectorizing {len(X_tr)} train rows ...")
    Xt = vec.fit_transform(X_tr)
    clf = LinearSVC(C=1.0, class_weight="balanced")
    print("Fitting LinearSVC ...")
    clf.fit(Xt, y_tr)

    preds = clf.predict(vec.transform(X_te))
    overall = {"accuracy": round(accuracy_score(y_te, preds), 4),
               "macro_f1": round(f1_score(y_te, preds, average="macro"), 4)}

    by_lang: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(test):
        by_lang[r["lang"]].append(i)
    per_lang = {}
    for lang, idxs in sorted(by_lang.items()):
        g = [y_te[i] for i in idxs]
        p = [preds[i] for i in idxs]
        per_lang[lang] = {"n": len(idxs),
                          "accuracy": round(accuracy_score(g, p), 4),
                          "macro_f1": round(f1_score(g, p, average="macro"), 4)}

    report = {"model": "tfidf(word1-2 + char2-5) + LinearSVC",
              "train_size": len(train), "test_size": len(test),
              "overall": overall, "per_language": per_lang}
    out = settings.MODELS_DIR.parent / "baseline_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'language':<10}{'n':>6}{'acc':>8}{'macroF1':>9}")
    print("-" * 33)
    for lang, m in per_lang.items():
        print(f"{lang:<10}{m['n']:>6}{m['accuracy']:>8.3f}{m['macro_f1']:>9.3f}")
    print(f"\noverall acc={overall['accuracy']:.3f}  macro_f1={overall['macro_f1']:.3f}")
    print(f"Report -> {out}")


if __name__ == "__main__":
    main()
