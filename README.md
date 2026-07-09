# Political Biases in Bosnian News

A machine learning project for analyzing Bosnian news articles across four politically relevant topics. The system first determines whether an article mentions a topic and then, for mentioned topics, predicts the article's stance as **for**, **neutral**, or **against**.

The repository contains the complete workflow: data collection and preparation, LLM-assisted annotation, supervised and unsupervised modelling, evaluation, and a Django web application for interactive article analysis.


## Datasets

The datasets used in this project are available in the following Google Drive folder:

### [Access the project datasets](https://drive.google.com/drive/folders/1fV5DFjzW3h7mpKA5HsKDFVvaOvCGSkmD?usp=sharing)

The folder includes:

- `novi_final_20k.csv` — the annotated dataset used for model training and evaluation;
- `svi_clanci.csv` — the combined corpus of collected news articles;
- `final_dataset.csv` — a processed project dataset;
- portal-specific datasets for Klix, RTRS, Stav, Dnevni Avaz, Buka, and Radio Sarajevo;
- filtered subsets created during data preparation.

Large datasets and trained model artifacts are not stored directly in this GitHub repository.

## Research task

The project analyzes coverage of the following topics:

| Internal key | Topic |
|---|---|
| `izborna_reforma` | Electoral reform |
| `negiranje_genocida` | Genocide denial |
| `gradjanska_vs_konstitutivni` | Civic vs. constituent model |
| `euroatlantske_integracije` | Euro-Atlantic integration |

For each article and topic, the pipeline performs two stages:

1. **Mention detection** — predicts whether the topic is mentioned.
2. **Stance classification** — for mentioned topics, predicts one of:
   - `for`
   - `neutral`
   - `against`

Articles that do not mention a topic receive the `not_mentioned` label.

## Data sources

The corpus contains articles from six Bosnian and regional news portals:

- Klix
- RTRS
- Stav
- Dnevni Avaz
- Buka
- Radio Sarajevo

The repository includes notebooks and scripts for scraping, cleaning, combining, filtering, deduplicating, and preparing the collected articles.

## Methodology

The project workflow consists of the following stages:

1. **Data collection**  
   News articles were collected from multiple portals through web scraping and previously available datasets.

2. **Data cleaning and preparation**  
   Articles were standardized, merged, deduplicated, and filtered using topic-related keywords.

3. **LLM-assisted annotation**  
   A selected sample was annotated for topic mention, stance, confidence, and supporting evidence. The annotation process was then used to create a larger labelled dataset.

4. **Supervised modelling**  
   Traditional linear text classifiers and transformer-based models were trained and compared.

5. **Unsupervised and semi-supervised analysis**  
   Topic modelling and clustering experiments were used to explore the structure of the larger unlabelled corpus.

6. **Evaluation and ensemble learning**  
   Individual models were evaluated on the same test splits. Logistic Regression and BERTić were also combined using equal-weight soft voting.

7. **Web application**  
   The final models were integrated into a Django application for interactive article analysis.

## Models

The project evaluates several approaches, including:

- Logistic Regression with TF-IDF features;
- SGD classifier with log-loss;
- SGD classifier with hinge loss;
- BERTić transformer models;
- soft-voting ensemble of Logistic Regression and BERTić;
- BERTopic and clustering-based experiments.

### Two-stage classification

The production pipeline is hierarchical:

```text
Article
  │
  ├── Topic not mentioned → not_mentioned
  │
  └── Topic mentioned
         └── Stance model → for / neutral / against
```

This structure reduces the need to perform stance classification on articles unrelated to a given topic.

### Soft-voting ensemble

For models that output class probabilities, the ensemble averages the probabilities produced by Logistic Regression and BERTić:

```text
ensemble_probability = 0.5 × logreg_probability + 0.5 × bertic_probability
```

The class with the highest averaged probability is selected as the final prediction. Soft voting is applied independently to the mention-detection and stance-classification stages.

## Repository structure

```text
political-biases-bosnian-news/
├── Data preparation/    # Scraping, cleaning, filtering and annotation
├── Modelling/           # Supervised, unsupervised and transformer models
├── Evaluation/          # Model evaluation, comparisons and inference
└── UI/                  # Django web application
    ├── config/          # Django settings, URLs, ASGI and WSGI
    ├── predictor/       # Prediction API, ML pipeline, scraping and frontend
    ├── models/          # Location for trained model artifacts
    ├── manage.py
    ├── requirements.txt
    └── requirements-ml.txt
```

## Running the web application locally

### 1. Clone the repository

```bash
git clone https://github.com/Seferovic8/political-biases-bosnian-news.git
cd political-biases-bosnian-news/UI
```

### 2. Create and activate a virtual environment

Linux or macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install the web application dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply Django migrations

```bash
python manage.py migrate
```

### 5. Start the development server

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Running with trained models

The trained model files are large and are therefore not included directly in the repository.

Install the additional machine learning dependencies:

```bash
pip install -r requirements-ml.txt
```

Place the model artifacts inside `UI/models/`, following the instructions in `UI/models/README.md`, or configure their locations with environment variables:

```bash
export MODELS_ROOT=/path/to/models

export LOGREG_BINARY_SOURCE=/path/to/models2
export LOGREG_STANCE_SOURCE=/path/to/models_stance
export BERT_BINARY_SOURCE=/path/to/bertic_models
export BERT_STANCE_SOURCE=/path/to/bertic_stance_models
```

On Windows PowerShell:

```powershell
$env:MODELS_ROOT="C:\path\to\models"
```

When trained artifacts are unavailable, the interface can run in demo mode using a deterministic fallback predictor. Demo mode demonstrates the application workflow but does not replace predictions from the trained models.

To force demo mode:

```bash
export FORCE_DEMO=1
```

## Supported article URLs

The web application can automatically extract the title and article body from supported portals, including:

- Klix
- RTRS
- Stav

Scraping depends on the current HTML structure of each portal. If a portal changes its website markup, its parser may need to be updated.

## Prediction API

The Django application exposes internal JSON endpoints used by the frontend:

```text
/api/status
/api/scrape
/api/predict
```

The prediction service automatically selects the live model engine when model artifacts are available and otherwise uses the demo fallback.

## Technologies

- Python
- pandas and NumPy
- scikit-learn
- PyTorch
- Hugging Face Transformers
- BERTić
- BERTopic
- Django
- Chart.js
- Beautiful Soup
- Railway

## Notes

- A database is not required for the main prediction workflow.
- BERTić uses the article title and body, while the linear models primarily use article text.
- The application supports batch analysis of multiple articles.
- Visualizations require browser access to the Chart.js CDN.
- The datasets and models can require substantial storage and memory.

## Intended use

This project was developed for research and educational purposes. Model outputs are probabilistic predictions and should not be treated as definitive assessments of an article, journalist, or media outlet. Results should be interpreted together with the original article and the limitations of the training data.
