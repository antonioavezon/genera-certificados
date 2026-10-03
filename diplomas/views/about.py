from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def about(request):
    return render(request, "diplomas/about.html")
