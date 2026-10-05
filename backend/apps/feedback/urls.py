from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("", views.feedback_list_view, name="list"),
    path("new/", views.feedback_create_view, name="create"),
    path("<int:pk>/edit/", views.feedback_edit_view, name="edit"),
    path("<int:pk>/delete/", views.feedback_delete_view, name="delete"),
]
