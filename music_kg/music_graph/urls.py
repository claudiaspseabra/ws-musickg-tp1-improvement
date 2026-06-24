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

    path('artist/<str:slug>/add-track/', views.add_track_view, name='add-track'),
    path('artist/<str:slug>/delete/', views.delete_artist_view, name='delete-artist'),

    path('album/<str:slug>/', views.album_detail, name='album-detail'),
    path('album/<str:slug>/edit/', views.edit_album_view, name='edit-album'),
    path('album/<str:slug>/delete/', views.delete_album_view, name='delete-album'),

    path('track/<str:slug>/delete/', views.delete_track_view, name='delete-track'),
]