from django.urls import path

from . import views

app_name = "predictor"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/status", views.api_status, name="api_status"),
    path("api/scrape", views.api_scrape, name="api_scrape"),
    path("api/predict", views.api_predict, name="api_predict"),
]
