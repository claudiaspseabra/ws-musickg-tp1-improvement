"""
music_graph/urls.py
Routing configuration for the Django SSR Frontend
"""
from django.urls import path
from music_graph import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('stats/', views.stats_view, name='stats'),
    path('timeline/', views.timeline_view, name='timeline'),
    path('explore/', views.explore_view, name='explore'),

    path('create-artist/', views.create_artist_view, name='create-artist'),
    path('artist/<str:slug>/', views.artist_detail, name='artist-detail'),
    path('artist/<str:slug>/add-track/', views.add_track_view, name='add-track'),
    path('artist/<str:slug>/delete/', views.delete_artist_view, name='delete-artist'),
    path('artist/<str:artist_slug>/create-album/', views.create_album_view, name='create-album'),

    path('artist/<str:slug>/raw/', views.raw_artist_view, name='raw-artist'),
    path('artist/<str:slug>/export/', views.export_artist_view, name='export-artist'),

    path('album/<str:slug>/', views.album_detail, name='album-detail'),
    path('album/<str:slug>/edit/', views.edit_album_view, name='edit-album'),
    path('album/<str:slug>/delete/', views.delete_album_view, name='delete-album'),
    path('album/<str:album_slug>/remove-track/<str:track_slug>/', views.remove_track_from_album_view, name='remove-track-from-album'),
    path('album/<str:album_slug>/add-existing-track/', views.add_existing_track_view, name='add-existing-track'),

    path('track/<str:slug>/delete/', views.delete_track_view, name='delete-track'),
    path('track/<str:slug>/edit/', views.edit_track_view, name='edit-track'),
    path('track/<str:slug>/vibe/', views.track_vibe_view, name='track-vibe'),
]
