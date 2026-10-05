from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.planner.services.state import is_super_admin

from .models import Feedback


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ["title", "description"]


def can_edit(user, item) -> bool:
    return is_super_admin(user) or item.created_by_id == user.id


def can_delete(user, item) -> bool:
    return can_edit(user, item)


@login_required
def feedback_list_view(request):
    items = list(Feedback.objects.select_related("created_by"))
    for item in items:
        item.can_edit = can_edit(request.user, item)
        item.can_delete = can_delete(request.user, item)
    return render(request, "feedback/list.html", {"items": items, "nav_section": "feedback"})


@login_required
def feedback_create_view(request):
    form = FeedbackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.created_by = request.user
        item.save()
        return redirect("feedback:list")
    return render(request, "feedback/create.html", {"form": form, "nav_section": "feedback"})


@login_required
def feedback_edit_view(request, pk):
    item = get_object_or_404(Feedback, pk=pk)
    if not can_edit(request.user, item):
        return HttpResponseForbidden("You can only edit your own feedback.")
    form = FeedbackForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("feedback:list")
    return render(
        request, "feedback/create.html", {"form": form, "item": item, "nav_section": "feedback"}
    )


@login_required
@require_POST
def feedback_delete_view(request, pk):
    item = get_object_or_404(Feedback, pk=pk)
    if not can_delete(request.user, item):
        return HttpResponseForbidden("You can only delete your own feedback.")
    item.delete()
    return redirect("feedback:list")
