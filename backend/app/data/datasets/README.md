# Training datasets — provenance

All sentiment training data comes from **real public datasets**, downloaded
from **kaggle.com**, **huggingface.co** and **github.com** by `python -m app.ml.download_datasets`
and kept in this folder **in their original file formats** (CSV / parquet /
JSONL / CoNLL — exactly as published, original filenames). Nothing here is
self-authored and nothing is converted: training (`app/ml/corpus.py`) reads
these raw files directly and builds the corpus in memory — no intermediate
JSON is ever written.

This folder is gitignored (hundreds of MB). One command restores it and
retrains everything: `python -m app.ml.bootstrap` (from `backend/`).

## Raw Kaggle datasets (`kaggle/`, downloaded from kaggle.com)

| Folder | Kaggle dataset | What it covers |
|---|---|---|
| `sentiment140/` | [kazanova/sentiment140](https://www.kaggle.com/datasets/kazanova/sentiment140) | Stanford Sentiment140 — 1.6M labeled tweets, 227 MB raw CSV (all-ages Twitter language) |
| `twitter-airline-sentiment/` | [crowdflower/twitter-airline-sentiment](https://www.kaggle.com/datasets/crowdflower/twitter-airline-sentiment) | 14.6k airline tweets — complaints/praise, plain adult register |
| `twitter-entity-sentiment-analysis/` | [jp797498e/twitter-entity-sentiment-analysis](https://www.kaggle.com/datasets/jp797498e/twitter-entity-sentiment-analysis) | 75k tweets about games/brands (Borderlands, FIFA, CS-GO…) — **Gen-Z / gamer slang register** |
| `twitter-and-reddit-sentimental-analysis-dataset/` | [cosmos98/twitter-and-reddit-sentimental-analysis-dataset](https://www.kaggle.com/datasets/cosmos98/twitter-and-reddit-sentimental-analysis-dataset) | 200k **Indian** political tweets + Reddit comments (rows our detector flags as code-mixed are trained as Hinglish) |
| `imdb-dataset-of-50k-movie-reviews/` | [lakshmi25npathi/imdb-dataset-of-50k-movie-reviews](https://www.kaggle.com/datasets/lakshmi25npathi/imdb-dataset-of-50k-movie-reviews) | 50k long-form movie reviews — formal / older-demographic register |
| `social-media-sentiments-analysis-dataset/` | [kashishparmar02/social-media-sentiments-analysis-dataset](https://www.kaggle.com/datasets/kashishparmar02/social-media-sentiments-analysis-dataset) | Instagram/Facebook/Twitter posts full of emojis + hashtags |

## Raw Hugging Face datasets (`huggingface/<org>/<name>/`)

| Dataset | Language | What it is |
|---|---|---|
| [cardiffnlp/tweet_eval](https://huggingface.co/datasets/cardiffnlp/tweet_eval) (`sentiment/`) | English | SemEval-2017 Twitter benchmark, 45k tweets |
| [google-research-datasets/go_emotions](https://huggingface.co/datasets/google-research-datasets/go_emotions) | English | 58k **Reddit comments** (slang-heavy, mapped to polarity via the GoEmotions paper's grouping) |
| [boltuix/emotions-dataset](https://huggingface.co/datasets/boltuix/emotions-dataset) | English | 131k casual internet/conversation texts, 13 emotions → polarity |
| [Sp1786/multiclass-sentiment-analysis-dataset](https://huggingface.co/datasets/Sp1786/multiclass-sentiment-analysis-dataset) | English | 31k 3-class posts |
| [MLBtrio/genz-slang-dataset](https://huggingface.co/datasets/MLBtrio/genz-slang-dataset) | English | 1.8k **Gen-Z slang terms** — used to measure slang coverage of the corpus (reported at every training run) |
| [mteb/tweet_sentiment_multilingual](https://huggingface.co/datasets/mteb/tweet_sentiment_multilingual) (`*/hindi.jsonl.gz`) | Hindi + romanized | Cardiff NLP tweet benchmark (romanized rows are routed to Hinglish by our detector) |
| [mteb/IndicSentiment](https://huggingface.co/datasets/mteb/IndicSentiment) (`*/hi,gu.jsonl.gz`) | Hindi, Gujarati | AI4Bharat product-review benchmark |
| [OdiaGenAI/sentiment_analysis_hindi](https://huggingface.co/datasets/OdiaGenAI/sentiment_analysis_hindi) | Hindi | 2.5k product reviews |
| [sepidmnorozy/Hindi_sentiment](https://huggingface.co/datasets/sepidmnorozy/Hindi_sentiment) | Hindi | movie reviews (binary) |
| [Process-Venue/Movie_Review_Sentiment_Hindi](https://huggingface.co/datasets/Process-Venue/Movie_Review_Sentiment_Hindi) | Hindi | 1k human-annotated reviews (labels in Hindi: सकारात्मक/नकारात्मक/तटस्थ) |
| [nikitadesai/gujaratiMovieSentiments](https://huggingface.co/datasets/nikitadesai/gujaratiMovieSentiments) | Gujarati | 3-class long movie reviews |
| [RTT1/SentiMix](https://huggingface.co/datasets/RTT1/SentiMix) | Hinglish | **SemEval-2020 Task 9** — the reference Hinglish corpus (17k, raw CoNLL token files) |
| [shae2977/hinglish-youtube-sentiments-dataset](https://huggingface.co/datasets/shae2977/hinglish-youtube-sentiments-dataset) | Hinglish | 3.2k real YouTube comments |
| [Abhishek4896/hindi-english-code-mixed-tweets-sentiment](https://huggingface.co/datasets/Abhishek4896/hindi-english-code-mixed-tweets-sentiment) | Hinglish | code-mixed tweets |
| [airzipm/sentiment-dataset-en-hi-hinglish-v2](https://huggingface.co/datasets/airzipm/sentiment-dataset-en-hi-hinglish-v2) | Hinglish | 97k mixed dump — only rows **our** language detector calls Hinglish are kept |

## Raw GitHub datasets (`github/`)

| Folder | Repo | What it is |
|---|---|---|
| `Gujlish-English-Translation/` | [mukund302002/Gujlish-English-Translation](https://github.com/mukund302002/Gujlish-English-Translation) | the only real Gujlish corpus anywhere: 30k English↔Gujlish parallel pairs (`English-Gujlish dataset.csv`) + 300 social-media-register sentences (`Social_media.csv`) |

## Groq LLM augmentation (`groq-augmented/`, optional)

With a free `GROQ_API_KEY` in `backend/.env`, `python -m app.ml.groq_augment`
adds register/language conversions **of real labeled rows** for all five
language forms — the LLM only converts language/register, labels always come
from real datasets or a documented LLM-labeling pass, never invented:

| Cache file | What it is | Used in |
|---|---|---|
| `gujlish_labeled_pairs.csv` | the REAL Gujlish sentences from the GitHub corpus above, sentiment-labeled by the LLM from their English side (confidence ≥ 0.8 only) | train + test |
| `gujlish.csv` | real Gujarati rows translated to colloquial Gujlish (label preserved) | train + test (per split) |
| `genz.csv` | real English rows rewritten in Gen-Z / brainrot social-media register (label preserved) | **train only** |
| `hindi.csv` | real English rows translated to casual social-media Hindi (label preserved) | **train only** |
| `gujarati.csv` | real English rows translated to casual Gujarati (label preserved) | **train only** |
| `hinglish.csv` | real English/Hindi rows translated to code-mixed Hinglish (label preserved) | **train only** |

Translation sources are sampled from the train split only, so nothing derived
from a test row can reach training — the held-out test set stays real.

**Fallback** (no key needed): Gujlish rows are the real Gujarati rows
transliterated mechanically by `app/ml/romanize.py` (source tag
`romanized(...)`); the other targets simply contribute nothing.

## Register coverage

Beyond languages, the mix deliberately spans **registers**: Gen-Z/gamer slang
(gaming tweets, Reddit), brainrot-era social media (emoji/hashtag posts,
YouTube/Reddit comments), Indian political Twitter, plain conversation, and
formal long-form reviews. `python -m app.ml.corpus` prints the per-language /
per-source table plus how many of the 1.8k Gen-Z slang dictionary terms occur
in the training corpus.
