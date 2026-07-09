"""HTTP views: one page + three JSON endpoints."""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .ml.constants import CLASS_META, METHOD_NAMES, METHODS, TOPIC_NAMES, TOPICS
from .ml.service import engine_status, predict_articles
from .scraping.portals import SUPPORTED_PORTALS
from .scraping.scraper import scrape_many

MAX_ARTICLES = 40
MAX_URLS = 40


def index(request):
    status = engine_status()
    context = {
        "status_json": json.dumps(status),
        "topics_json": json.dumps(
            [{"key": t, "name": TOPIC_NAMES[t]} for t in TOPICS]
        ),
        "class_meta_json": json.dumps(CLASS_META),
        "method_names_json": json.dumps(METHOD_NAMES),
        "supported_portals": SUPPORTED_PORTALS,
    }
    return render(request, "predictor/index.html", context)


@require_GET
def api_status(request):
    return JsonResponse(engine_status())


def _parse_json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None


@require_POST
def api_scrape(request):
    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        return JsonResponse(
            {"error": "Provide a non-empty list of URLs under 'urls'."},
            status=400,
        )

    urls = [str(u).strip() for u in urls if str(u).strip()]
    if not urls:
        return JsonResponse({"error": "No usable URLs were provided."}, status=400)
    if len(urls) > MAX_URLS:
        return JsonResponse(
            {"error": f"Too many URLs (max {MAX_URLS} per request)."},
            status=400,
        )

    results = scrape_many(urls)
    return JsonResponse({"articles": results})


@require_POST
def api_predict(request):
    payload = _parse_json(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    method = payload.get("method")
    if method not in METHODS:
        return JsonResponse(
            {"error": f"Choose a method: {', '.join(METHODS)}."}, status=400
        )

    articles = payload.get("articles")
    if not isinstance(articles, list) or not articles:
        return JsonResponse(
            {"error": "Add at least one article before predicting."},
            status=400,
        )
    if len(articles) > MAX_ARTICLES:
        return JsonResponse(
            {"error": f"Too many articles (max {MAX_ARTICLES} per request)."},
            status=400,
        )

    cleaned = []
    errors = []
    for i, art in enumerate(articles):
        title = str((art or {}).get("title", "")).strip()
        content = str((art or {}).get("content", "")).strip()
        source = str((art or {}).get("source", "manual")).strip() or "manual"
        if not content:
            errors.append(f"Article {i + 1} has no text and was skipped.")
            continue
        cleaned.append({"title": title, "content": content, "source": source})

    if not cleaned:
        return JsonResponse(
            {"error": "None of the articles had any text to analyse.",
             "details": errors},
            status=400,
        )

    try:
        output = predict_articles(cleaned, method)
    except Exception as exc:  # surface a clean message to the UI
        return JsonResponse(
            {"error": f"Prediction failed: {exc}"}, status=500
        )

    output["method_name"] = METHOD_NAMES[method]
    output["skipped"] = errors
    return JsonResponse(output)
