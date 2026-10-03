from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from diplomas.services.dashboard_service import build_dashboard
from diplomas.views.generate import start_generation


@require_http_methods(["GET", "POST"])
def home(request):
    if request.method == "POST":
        return _run_from_home(request)
    return render(request, "diplomas/home.html", build_dashboard())


def _run_from_home(request):
    return start_generation(request, send_email=request.POST.get("action") == "send")
