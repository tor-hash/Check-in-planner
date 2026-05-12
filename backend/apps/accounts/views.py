from django.contrib.auth.decorators import login_required
from django.http import JsonResponse


@login_required
def profile_view(request):
    return JsonResponse(
        {
            "id": request.user.id,
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.get_username(),
        }
    )
