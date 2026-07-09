"""
Topic / class definitions.

These mirror the constants used across ``evaluation_logreg_bertic_ensemble.ipynb``
and ``inferencija_svi_clanci.ipynb`` so the web application classifies articles
with exactly the same label space and conventions as the notebooks.
"""

TOPICS = [
    "euroatlantske_integracije",
    "negiranje_genocida",
    "gradjanska_vs_konstitutivni",
    "izborna_reforma",
]

# Human-readable names shown in the UI.
TOPIC_NAMES = {
    "euroatlantske_integracije": "Euro-Atlantic Integration",
    "negiranje_genocida": "Genocide Denial",
    "gradjanska_vs_konstitutivni": "Civic vs. Constituent Model",
    "izborna_reforma": "Electoral Reform",
}

BINARY_CLASSES = ["not_mentioned", "mentioned"]
STANCE_CLASSES = ["against", "neutral", "for"]
FOUR_CLASSES = ["not_mentioned", "against", "neutral", "for"]

# Prediction methods exposed to the user.
METHODS = ["logreg", "bertic", "ensemble"]

METHOD_NAMES = {
    "logreg": "LogReg",
    "bertic": "BERTić",
    "ensemble": "Ensemble",
}

# Display metadata for the four final classes (colours are also defined in CSS
# and kept in sync there; this copy is used for any server-rendered fallback).
CLASS_META = {
    "not_mentioned": {"label": "Not mentioned", "color": "#9AA0A6"},
    "against": {"label": "Against", "color": "#C24A3A"},
    "neutral": {"label": "Neutral", "color": "#C99A2E"},
    "for": {"label": "For", "color": "#1F8A70"},
}

# Numeric value used to place a topic on the stance axis (against .. for).
STANCE_AXIS = {"against": -1.0, "neutral": 0.0, "for": 1.0}
