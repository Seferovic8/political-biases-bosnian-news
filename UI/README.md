# Stav — Article Stance Analysis

A Django web application that predicts, for Bosnian/regional news articles,
whether four political topics are **mentioned** and, if so, the **stance**
(*for* / *neutral* / *against*). It uses the same two-stage LogReg / BERTić /
ensemble pipeline as the reference notebooks
(`evaluation_logreg_bertic_ensemble.ipynb`, `inferencija_svi_clanci.ipynb`).

Topics:

| key | name |
|-----|------|
| `euroatlantske_integracije` | Euro-Atlantic Integration |
| `negiranje_genocida` | Genocide Denial |
| `gradjanska_vs_konstitutivni` | Civic vs. Constituent Model |
| `izborna_reforma` | Electoral Reform |

## What it does

1. **Model selection** — LogReg, BERTić, or the soft-vote Ensemble.
2. **Two input methods**
   * type/paste one or more articles (each becomes an editable card), or
   * paste article URLs from **RTRS**, **Klix**, or **Stav** and let the app
     scrape the title + body automatically (using the exact selectors from the
     reference scrapers).
3. **Queue management** — review, edit, or remove any article before running.
4. **Per-article results** — predicted class badge, confidence, a stance meter
   per topic, and (for the ensemble) a LogReg-vs-BERTić readout.
5. **Combined analysis** — final-label distribution, per-topic mention rate and
   net stance, an ensemble model-comparison, and an articles × topics heatmap,
   mirroring the aggregation in `inferencija_svi_clanci.ipynb`.

## Running it

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py runserver
# open http://127.0.0.1:8000/
```

That is enough to use the whole interface in **demo mode**.

### Demo mode vs. live models

The trained model files are large and are **not** bundled. When they are
absent the app runs a deterministic keyword heuristic (clearly labelled
*Demo mode* in the header) so every screen is fully demonstrable. The demo is
**not** a trained model — it only illustrates the flow and visualisations.

To run the **real** models:

```bash
pip install -r requirements-ml.txt        # torch, transformers, sklearn, …
```

Then place the artefacts under `models/` (see `models/README.md`) or point the
environment variables at their location:

```bash
export MODELS_ROOT=/path/to/models
# or override individually:
export LOGREG_BINARY_SOURCE=/path/to/models2
export LOGREG_STANCE_SOURCE=/path/to/models_stance
export BERT_BINARY_SOURCE=/path/to/bertic_models
export BERT_STANCE_SOURCE=/path/to/bertic_stance_models
```

The header will switch to **Live models** and predictions will be identical to
the notebooks:

* LogReg reads the article body (`SADRZAJ`).
* BERTić reads `title + ". " + body`.
* Binary stage → mentioned/not; stance stage runs only on mentioned articles.
* Ensemble = `0.5 · LogReg + 0.5 · BERTić` soft-vote (weights configurable).

Set `FORCE_DEMO=1` to force demo mode even when models are present.

## Project layout

```
config/                  Django project (settings, urls, wsgi/asgi)
predictor/
├── views.py             page + JSON API (/api/status, /api/scrape, /api/predict)
├── ml/
│   ├── constants.py     topics / classes (mirrors the notebooks)
│   ├── engine.py        real model loading + two-stage prediction
│   ├── demo.py          deterministic fallback predictor
│   ├── aggregate.py     combined multi-article analysis
│   └── service.py       chooses real engine vs. demo
├── scraping/            RTRS / Klix / Stav parsers (from the reference scripts)
├── templates/predictor/index.html
└── static/predictor/    app.css, app.js
models/                  drop trained artefacts here
```

## Notes

* No database is required.
* The scrapers depend on the live portal markup; if a portal changes its HTML,
  extraction may need updating. Failures are reported per-URL and never break a
  batch.
* Chart rendering uses Chart.js from a CDN, so the results view needs internet
  access in the browser.
