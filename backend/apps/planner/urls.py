from django.urls import path

from . import api, views

app_name = "planner"


urlpatterns = [
    path("", views.root_redirect, name="root"),
    path("healthz", views.healthz_view, name="healthz"),
    path("home/", views.home_view, name="home"),
    path("app/", views.app_view, name="app"),
    path("manager/settings/", views.manager_settings_view, name="manager-settings"),

    # Aggregate state (legacy contract — read still preferred for boot)
    path("api/state", api.state_get, name="api-state-get"),
    path("api/state/update", api.state_put, name="api-state-put"),
    path("api/state/<str:key>", api.state_key_get, name="api-state-key-get"),

    # People
    path("api/people", api.people_collection, name="api-people-collection"),
    path("api/people/<str:person_id>", api.people_detail, name="api-people-detail"),

    # Projects
    path("api/projects", api.projects_collection, name="api-projects-collection"),
    path("api/projects/<str:name>", api.projects_detail, name="api-projects-detail"),

    # Function tags
    path("api/function-tags", api.function_tags_collection, name="api-function-tags-collection"),

    # Teams
    path("api/teams/<str:team>", api.teams_membership_put, name="api-teams-membership-put"),

    # Managers
    path("api/managers", api.managers_collection, name="api-managers-collection"),
    path("api/managers/<str:manager_id>", api.managers_detail, name="api-managers-detail"),
    path("api/managers/<str:manager_id>/settings", api.manager_settings, name="api-manager-settings"),

    # Journal entries + attachments
    path("api/journal-entries", api.journal_collection, name="api-journal-collection"),
    path("api/journal-entries/<str:entry_id>", api.journal_detail, name="api-journal-detail"),
    path(
        "api/journal-entries/<str:entry_id>/files",
        api.journal_file_upload,
        name="api-journal-file-upload",
    ),
    path(
        "api/journal-entries/<str:entry_id>/files/<int:file_id>",
        api.journal_file_delete,
        name="api-journal-file-delete",
    ),

    # Planner config + custom dates
    path("api/config", api.config_endpoint, name="api-config"),
    path("api/custom-dates", api.custom_dates_endpoint, name="api-custom-dates"),

    # Server-side Google Calendar
    path("api/freebusy", api.freebusy_endpoint, name="api-freebusy"),
    path(
        "api/calendar-share-requests",
        api.calendar_share_requests,
        name="api-calendar-share-requests",
    ),
    path("api/bookings", api.bookings_collection, name="api-bookings-collection"),
    path("api/bookings/<int:booking_id>", api.bookings_detail, name="api-bookings-detail"),
    path("api/bookings/<int:booking_id>/rebook", api.bookings_rebook, name="api-bookings-rebook"),

    # Notifications
    path("api/notifications", api.notifications_collection, name="api-notifications-collection"),
    path("api/notifications/<int:notification_id>/read", api.notification_mark_read, name="api-notification-mark-read"),
    path("api/notifications/read-all", api.notifications_mark_all_read, name="api-notifications-read-all"),

    # Rotation / session windows
    path("api/rotation", api.rotation_endpoint, name="api-rotation"),
]
