from django.urls import path
from . import views, notice_views, generation_views

urlpatterns = [
    path('notices/', notice_views.detail),
    path('generations/<str:generation>/export/', generation_views.export_provenance),
    path('generations/<str:generation>/', generation_views.detail),
    path('reports/<uuid:host_id>/notices/', notice_views.ingest),
    path('mirrors/', views.mirrors),
    path('items/', views.items),
    path('reports/<uuid:host_id>/', views.report),
]
