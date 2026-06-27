"""
music_graph/views.py
"""
from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse, JsonResponse
from django.contrib import messages

from music_graph import sparql_queries as sq
from music_graph.rdf_store import store

import json

# HOME / SEARCH / STATS

def home(request):
    """Home page displaying real-time GraphDB statistics."""
    stats = store.get_stats()

    if store.using_graphdb:
        stats["total_triples"] = store._graphdb_triple_count()

        r_art = store.execute_sparql(
            "SELECT (COUNT(DISTINCT ?a) AS ?c) WHERE { ?a <http://musickg.org/data/artistName> ?n }")
        stats["unique_artists"] = r_art[0]["c"] if r_art else 0

        r_trk = store.execute_sparql(
            "SELECT (COUNT(DISTINCT ?t) AS ?c) WHERE { ?t <http://musickg.org/data/trackName> ?n }")
        stats["unique_tracks"] = r_trk[0]["c"] if r_trk else 0

        r_alb = store.execute_sparql(
            "SELECT (COUNT(DISTINCT ?a) AS ?c) WHERE { ?a <http://musickg.org/data/albumName> ?n }")
        stats["unique_albums"] = r_alb[0]["c"] if r_alb else 0
    else:
        stats["total_triples"] = 0
        stats["unique_artists"] = 0
        stats["unique_tracks"] = 0
        stats["unique_albums"] = "N/A"
    return render(request, 'music_graph/home.html', {'stats': stats})

def search(request):
    """Search page with type filters and artist creation."""
    q = request.GET.get('q', '').strip()
    entity_type = request.GET.get('type', 'all')

    results = []
    total_count = 0
    can_create_artist = False

    if q:
        search_type = entity_type if entity_type != 'all' else None
        search_data = sq.full_text_search(q, entity_type=search_type, limit=50)
        results = search_data.get("results", [])
        total_count = search_data.get("total_count", 0)

        if entity_type in ['all', 'artist']:
            if not sq.ask_artist_exists(q):
                can_create_artist = True

    context = {
        'query': q,
        'current_type': entity_type,
        'results': results,
        'total_count': total_count,
        'can_create_artist': can_create_artist,
    }
    return render(request, 'music_graph/search.html', context)

def stats_view(request):
    """Statistics dashboard."""
    top_genres_data = sq.get_top_genres_stats(10)
    energy_data = sq.get_avg_energy_by_genre(10)

    context = {
        # Chart 1: Top Genres
        'g1_labels': json.dumps([item["label"] for item in top_genres_data]),
        'g1_data': json.dumps([item["count"] for item in top_genres_data]),

        # Chart 2: Average Energy
        'g2_labels': json.dumps([item["label"] for item in energy_data]),
        'g2_data': json.dumps([item["avg"] for item in energy_data]),
    }

    return render(request, 'music_graph/stats.html', context)

# ARTIST / TRACK / ALBUM

def artist_detail(request, slug):
    """Detailed view for a specific artist."""
    artist_data = sq.get_artist_detail(slug)
    if not artist_data:
        raise Http404("Artist not found in the Knowledge Graph.")

    context = {
        'artist': artist_data,
    }
    return render(request, 'music_graph/artist_detail.html', context)

def create_artist_view(request):
    """Handles POST requests to create a new artist entity."""
    if request.method == "POST":
        artist_name = request.POST.get("artist_name")
        if artist_name:
            if not sq.ask_artist_exists(artist_name):
                slug = sq.create_new_artist(artist_name)
                messages.success(request, f"Artist '{artist_name}' created and added to the Graph!")
                return redirect('artist-detail', slug=slug)
            else:
                messages.warning(request, "This artist already exists in the system.")
    return redirect('search')

def delete_artist_view(request, slug):
    """Handles POST requests to delete an artist and related entities."""
    if request.method == "POST":
        if sq.delete_artist(slug):
            messages.success(request, "Artist successfully deleted!")
            return redirect('home')
        else:
            messages.error(request, "Error deleting artist.")
    return redirect('artist-detail', slug=slug)

def add_track_view(request, slug):
    """Handles POST requests to add a new track to an artist."""
    if request.method == "POST":
        track_name = request.POST.get("track_name")
        genre_name = request.POST.get("genre_name")
        energy = request.POST.get("energy", 0.5)
        album_slug = request.POST.get("album_slug")


        if sq.ask_track_exists(slug, track_name):
            messages.warning(request, f"The track '{track_name}' already exists for this artist!")
        else:
            if sq.add_new_track(slug, track_name, genre_name, float(energy), album_slug):
                messages.success(request, f"Track '{track_name}' successfully created!")
            else:
                messages.error(request, "Error creating track.")

        if album_slug:
            return redirect('album-detail', slug=album_slug)
    return redirect('artist-detail', slug=slug)

def edit_track_view(request, slug):
    """Handles POST requests to update track metadata."""
    if request.method == "POST":
        track_name = request.POST.get("track_name")
        genre_name = request.POST.get("genre_name")
        energy = request.POST.get("energy")
        track_number = request.POST.get("track_number")

        if sq.update_track(slug, track_name, genre_name, float(energy), track_number):
            messages.success(request, f"Track '{track_name}' updated!")
        else:
            messages.error(request, "Error updating the track.")

        previous_url = request.META.get('HTTP_REFERER')
        if previous_url:
            return redirect(previous_url)

        artist_slug = request.POST.get("artist_slug")
        album_slug = request.POST.get("album_slug")

        if album_slug:
            return redirect('album-detail', slug=album_slug)
        if artist_slug:
            return redirect('artist-detail', slug=artist_slug)

    return redirect('home')

def delete_track_view(request, slug):
    """Handles POST requests to delete a track entity."""
    if request.method == "POST":
        artist_slug = request.POST.get("artist_slug")
        album_slug = request.POST.get("album_slug")

        if sq.delete_track(slug):
            messages.success(request, "Track permanently deleted from the system!")
        else:
            messages.error(request, "Error deleting the track.")

        previous_url = request.META.get('HTTP_REFERER')
        if previous_url:
            return redirect(previous_url)

        if album_slug:
            return redirect('album-detail', slug=album_slug)
        if artist_slug:
            return redirect('artist-detail', slug=artist_slug)
    return redirect('home')

def album_detail(request, slug):
    """Detailed view for a specific album node."""
    album_data = sq.get_album_detail(slug)
    if not album_data:
        raise Http404("Album not found.")
    return render(request, 'music_graph/album_detail.html', {'album': album_data})

def create_album_view(request, artist_slug):
    """Handles POST request to create a new album for a given artist."""
    if request.method == "POST":
        album_name = request.POST.get("album_name", "").strip()
        release_year_str = request.POST.get("release_year", "2024").strip()

        if album_name and release_year_str.isdigit():
            # check if the album already exists using the ASK constraint
            if sq.ask_album_exists(artist_slug, album_name):
                messages.warning(request, f"The album '{album_name}' already exists in the Graph for this artist!")
                return redirect('artist-detail', slug=artist_slug)

            # if it does not exist, initialize it in the Graph
            album_slug = sq.create_new_album(
                artist_slug,
                album_name,
                int(release_year_str)
            )

            messages.success(request, f"Album '{album_name}' successfully created in the Graph!")
            return redirect('album-detail', slug=album_slug)

        messages.error(request, "Invalid album data provided.")

    return redirect('artist-detail', slug=artist_slug)

def edit_album_view(request, slug):
    """Handles POST requests to update album metadata."""
    if request.method == "POST":
        new_name = request.POST.get("album_name")
        new_year = request.POST.get("release_year")
        if sq.update_album(slug, new_name, int(new_year)):
            messages.success(request, "Album successfully updated!")
        else:
            messages.error(request, "Error updating the album.")
    return redirect('album-detail', slug=slug)

def delete_album_view(request, slug):
    """Handles POST requests to remove an album node."""
    if request.method == "POST":
        artist_slug = request.POST.get("artist_slug")
        if sq.delete_album(slug):
            messages.success(request, "Album successfully deleted!")
            if artist_slug:
                return redirect('artist-detail', slug=artist_slug)
            return redirect('home')
        else:
            messages.error(request, "Error deleting the album.")
    return redirect('home')

def add_existing_track_view(request, album_slug):
    """Handles POST requests to link an existing track to an album."""
    if request.method == "POST":
        track_slug = request.POST.get("track_slug")
        if track_slug and sq.add_existing_track_to_album(track_slug, album_slug):
            messages.success(request, "Track successfully linked to this album!")
        else:
            messages.error(request, "Error linking the track.")
    return redirect('album-detail', slug=album_slug)

def remove_track_from_album_view(request, album_slug, track_slug):
    """Handles POST requests to delete the relationship between a track and an album."""
    if request.method == "POST":
        if sq.remove_track_from_album(track_slug, album_slug):
            messages.success(request, "Track removed from album. It remains in the system as a song.")
        else:
            messages.error(request, "Error removing track from album.")
    return redirect('album-detail', slug=album_slug)

# DESCRIBE / CONSTRUCT

def raw_artist_view(request, slug):
    """Returns raw RDF serialization via DESCRIBE."""
    rdf_data = sq.describe_artist(slug)
    return HttpResponse(rdf_data, content_type="text/plain; charset=utf-8")

def export_artist_view(request, slug):
    """Returns a downloadable TTL file via CONSTRUCT sub-graph queries."""
    rdf_data = sq.construct_artist_export(slug)
    response = HttpResponse(rdf_data, content_type="text/turtle; charset=utf-8")
    response['Content-Disposition'] = f'attachment; filename="artist_{slug}.ttl"'
    return response

# DISCOVERY / ANALYTICS

def track_vibe_view(request, slug):
    """View for discovering tracks with similar semantic and audio metrics."""
    vibe_data = sq.get_track_vibe_recommendations(slug)
    if not vibe_data:
        raise Http404("Track not found for Vibe analysis.")
    return render(request, 'music_graph/track_vibe.html', {'track': vibe_data})

def timeline_view(request):
    """Chronological explorer with paginated limits and combined parameter filters."""
    decade = request.GET.get('decade')
    letter = request.GET.get('letter')
    offset = int(request.GET.get('offset', 0))
    limit = 25

    albums = sq.get_paginated_timeline(decade=decade, letter=letter, offset=offset, limit=limit)

    next_offset = offset + limit if len(albums) == limit else None

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'albums': albums,
            'next_offset': next_offset
        })

    context = {
        'timeline': albums,
        'decade': decade,
        'letter': letter,
        'offset': offset,
        'next_offset': next_offset,
        'alphabet': "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        'decades': [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]
    }
    return render(request, 'music_graph/timeline.html', context)

def explore_view(request):
    """Advanced Audio Discovery Explorer."""
    selected_genre = request.GET.get('genre', 'all')
    min_e = request.GET.get('min_energy', '0.0')
    max_e = request.GET.get('max_energy', '1.0')

    try:
        min_energy = float(min_e)
        max_energy = float(max_e)
    except ValueError:
        min_energy, max_energy = 0.0, 1.0

    all_genres = sq.get_all_genres()
    results = sq.explore_audio(selected_genre, min_energy, max_energy, limit=50)

    context = {
        'genres': all_genres,
        'selected_genre': selected_genre,
        'min_energy': min_energy,
        'max_energy': max_energy,
        'results': results,
        'total_count': len(results)
    }
    return render(request, 'music_graph/explore.html', context)
