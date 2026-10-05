from django.urls import path

from . import api, manage_api, views

app_name = "onboarding"

urlpatterns = [
    path("onboarding/flows/", views.flows_editor_view, name="flows-editor"),
    path("onboarding/drive/connect/", views.drive_connect_view, name="drive-connect"),
    path(
        "api/onboarding/manage/settings",
        manage_api.onboarding_settings,
        name="manage-settings",
    ),
    path(
        "api/onboarding/manage/employees/<str:erp_id>/documents",
        manage_api.employee_documents,
        name="manage-employee-documents",
    ),
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
        "api/onboarding/manage/welcome-emails",
        manage_api.welcome_emails_collection,
        name="manage-welcome-emails-collection",
    ),
    path(
        "api/onboarding/manage/welcome-emails/preview",
        manage_api.welcome_email_preview,
        name="manage-welcome-email-preview",
    ),
    path(
        "api/onboarding/manage/welcome-emails/<int:template_id>",
        manage_api.welcome_emails_detail,
        name="manage-welcome-emails-detail",
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
    path(
        "api/onboarding/manage/employees/<str:erp_id>/assign-flow",
        manage_api.assign_flow,
        name="manage-assign-flow",
    ),
    path(
        "api/onboarding/manage/employees/<str:erp_id>/book-calendar-meetings",
        manage_api.book_calendar_meetings,
        name="manage-book-calendar-meetings",
    ),
    path(
        "api/onboarding/manage/people",
        manage_api.people_list,
        name="manage-people-list",
    ),
    path(
        "api/onboarding/manage/people/<str:legacy_id>/roles",
        manage_api.person_roles,
        name="manage-person-roles",
    ),
    path("api/onboarding/provision", api.provision_employee, name="provision-employee"),
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
