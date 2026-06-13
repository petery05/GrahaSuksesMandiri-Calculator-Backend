from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('quotes', views.QuoteViewSet, basename='quote')

urlpatterns = [
    path('health/', views.health, name='health'),
    path('auth/me/', views.me, name='auth-me'),
    path('auth/login/', views.login_view, name='auth-login'),
    path('auth/logout/', views.logout_view, name='auth-logout'),
    path('catalog/', views.catalog, name='catalog'),
    path('compute/', views.compute, name='compute'),
    path('', include(router.urls)),
]
