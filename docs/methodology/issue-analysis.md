# Issue analysis methodology

Measures **topic frequency** in licensed/permitted text — not sentiment, support, or voting intention.
* Sources must permit text analysis (licence flag enforced at ingestion); items with author fields are rejected.
* De-duplication on body text: exact hash, then MinHash (5-word shingles, 64 permutations) with Jaccard ≥ 0.8
  within ±3 days (syndicated copies usually change headlines). Duplicates are excluded from counts and reported.
* Language: sentence-level stopword voting (en, es, fr, de, pt); documents with a second language ≥ 25% are
  `mixed`. Classifier: bilingual (en/es) lexicon taxonomy `2026.1`, model `lexicon-1.0.0` (versioned in
  `model_versions`; outputs keyed by model version).
* Geography only from source metadata (`geo_confidence`); coverage, languages and confidence are shown with
  every view. Weekly cells with fewer than 5 documents are suppressed.
* Human review: a review queue and labels (`topic_labels`, eval/dev splits) feed precision/recall/F1 by topic.
  Current labels are **generator truth on synthetic text**: micro-F1 is not evidence of real-world accuracy.
* Not implemented: sentiment/stance models (no validated model), languages beyond en/es for topics.
