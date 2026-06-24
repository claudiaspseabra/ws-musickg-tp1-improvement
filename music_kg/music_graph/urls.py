"""
music_graph/urls.py
Rotas para o frontend Django SSR (TP1)
"""
from django.urls import path
from music_graph import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('artist/<str:slug>/', views.artist_detail, name='artist-detail'),
]