from django.urls import path

from . import api, manage_api, views

app_name = "onboarding"

urlpatterns = [
    path("onboarding/flows/", views.flows_editor_view, name="flows-editor"),
    path(
        "api/onboarding/manage/component-types",
        manage_api.component_types,
        name="manage-component-types",
    ),
    path(
        "api/onboarding/manage/flows",
        manage_api.flows_collection,
        name="manage-flows-collection",
    ),
    path(
        "api/onboarding/manage/flows/<slug:slug>",
        manage_api.flows_detail,
        name="manage-flows-detail",
    ),
    path(
        "api/onboarding/manage/flows/<slug:slug>/steps",
        manage_api.steps_collection,
        name="manage-steps-collection",
    ),
    path(
        "api/onboarding/manage/flows/<slug:slug>/steps/reorder",
        manage_api.steps_reorder,
        name="manage-steps-reorder",
    ),
    path(
        "api/onboarding/manage/flows/<slug:slug>/steps/<int:step_id>",
        manage_api.steps_detail,
        name="manage-steps-detail",
    ),
    path(
        "api/onboarding/manage/employees",
        manage_api.employees_collection,
        name="manage-employees-collection",
    ),
    path(
        "api/onboarding/manage/employees/<str:erp_id>",
        manage_api.employees_detail,
        name="manage-employees-detail",
    ),
    path("api/onboarding/employees", api.employees_collection, name="employees-collection"),
    path(
        "api/onboarding/employees/by-email",
        api.employees_by_email,
        name="employees-by-email",
    ),
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
