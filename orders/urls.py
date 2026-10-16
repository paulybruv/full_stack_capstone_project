from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('vectorizer/', views.vectorizer_studio, name='vectorizer'),
    path('street-signs/', views.street_signs, name='street_signs'),
    path('api/process-preview/', views.process_preview_api, name='process_preview_api'),
    path('api/submit-order/', views.submit_order_api, name='submit_order_api'),
    path('api/unlock-digital-svg/', views.unlock_digital_svg_api, name='unlock_digital_svg_api'),
    path('api/download-svg/<uuid:token>/', views.download_svg_once, name='download_svg_once'),
]
