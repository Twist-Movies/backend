"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from apps.accounts.views import FollowView, FollowersListView, FollowingListView, MeView
from apps.movies.review_views import UserReviewListView
from apps.movies.user_views import UserSearchView

def healthz(request):
    """Health check do Render: sem auth, sem throttle e sem tocar no banco."""
    return HttpResponse('ok', content_type='text/plain')


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/accounts/", include("apps.accounts.urls")),
    path('api/users/me/', MeView.as_view(), name='user-me'),
    path('api/users/<int:id>/follow/', FollowView.as_view(), name='user-follow'),

    path('api/users/<int:id>/followers/', FollowersListView.as_view(), name='user-followers'),
    path('api/users/<int:id>/following/', FollowingListView.as_view(), name='user-following'),

    # Rotas de usuário implementadas em apps.movies (comentários e busca)
    path('api/users/search/', UserSearchView.as_view(), name='user-search'),
    path('api/users/<int:id>/reviews/', UserReviewListView.as_view(), name='user-reviews'),

    path('api/', include('apps.movies.urls')),
]

# Documentação da API: só com DEBUG ou ENABLE_DOCS=True.
if settings.DEBUG or settings.ENABLE_DOCS:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
