from django.urls import path

from . import api

app_name = "onboarding"

urlpatterns = [
    path("api/onboarding/employees", api.employees_collection, name="employees-collection"),
    path(
        "api/onboarding/employees/<str:erp_id>",
        api.employees_detail,
        name="employees-detail",
    ),
    path(
        "api/onboarding/employees/<str:erp_id>/steps/<int:step_id>",
        api.step_progress_detail,
        name="step-progress-detail",
    ),
    path("api/onboarding/flows", api.flows_collection, name="flows-collection"),
    path("api/onboarding/flows/<slug:slug>", api.flows_detail, name="flows-detail"),
]
