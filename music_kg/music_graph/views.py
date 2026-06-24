"""
music_graph/views.py
Django Server-Side Rendered Views adaptadas para o Fact Graph (TP1)
"""
from django.shortcuts import render, redirect
from django.http import Http404
from django.contrib import messages

from music_graph import sparql_queries as sq
from music_graph.rdf_store import store

def home(request):
    """Página inicial com as estatísticas em tempo real do GraphDB."""
    stats = store.get_stats()

    if store.using_graphdb:
        stats["total_triples"] = store._graphdb_triple_count()

        r_art = store.execute_sparql(
            "SELECT (COUNT(DISTINCT ?a) AS ?c) WHERE { ?a <http://musickg.org/data/artistName> ?n }")
        stats["unique_artists"] = r_art[0]["c"] if r_art else 0

        r_trk = store.execute_sparql(
            "SELECT (COUNT(DISTINCT ?t) AS ?c) WHERE { ?t <http://musickg.org/data/trackName> ?n }")
        stats["unique_tracks"] = r_trk[0]["c"] if r_trk else 0

        # NOVO: Contar Álbuns!
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
    """Página de pesquisa simplificada."""
    q = request.GET.get('q', '').strip()

    results = []
    total_count = 0

    if q:
        # Assinatura corrigida! Já não enviamos o 'genre'
        search_data = sq.full_text_search(q, limit=50)
        results = search_data.get("results", [])
        total_count = search_data.get("total_count", 0)

    context = {
        'query': q,
        'results': results,
        'total_count': total_count,
    }
    return render(request, 'music_graph/search.html', context)


def artist_detail(request, slug):
    """Página de detalhes de um artista."""
    artist_data = sq.get_artist_detail(slug)
    if not artist_data:
        raise Http404("Artista não encontrado no Knowledge Graph.")

    context = {
        'artist': artist_data,
    }
    return render(request, 'music_graph/artist_detail.html', context)


def add_track_view(request, slug):
    if request.method == "POST":
        track_name = request.POST.get("track_name")
        genre_name = request.POST.get("genre_name")
        energy = request.POST.get("energy", 0.5)
        artist_uri = f"http://musickg.org/artist/{slug}"

        if sq.add_new_track(artist_uri, track_name, genre_name, float(energy)):
            messages.success(request, f"Faixa '{track_name}' adicionada com sucesso!")
        else:
            messages.error(request, "Erro ao adicionar a faixa.")

    return redirect('artist-detail', slug=slug)


def delete_artist_view(request, slug):
    if request.method == "POST":
        artist_uri = f"http://musickg.org/artist/{slug}"
        if sq.delete_artist(artist_uri):
            messages.success(request, "Artista eliminado com sucesso!")
            return redirect('home')
        else:
            messages.error(request, "Erro ao eliminar o artista.")
    return redirect('artist-detail', slug=slug)

# --- NOVAS VIEWS PARA ÁLBUNS E FAIXAS ---

def album_detail(request, slug):
    album_data = sq.get_album_detail(slug)
    if not album_data:
        raise Http404("Álbum não encontrado.")
    return render(request, 'music_graph/album_detail.html', {'album': album_data})

def edit_album_view(request, slug):
    if request.method == "POST":
        new_name = request.POST.get("album_name")
        new_year = request.POST.get("release_year")
        if sq.update_album(slug, new_name, int(new_year)):
            messages.success(request, "Álbum atualizado com sucesso!")
        else:
            messages.error(request, "Erro ao atualizar o álbum.")
    return redirect('album-detail', slug=slug)

def delete_album_view(request, slug):
    if request.method == "POST":
        artist_slug = request.POST.get("artist_slug") # Para sabermos para onde redirecionar
        if sq.delete_album(slug):
            messages.success(request, "Álbum eliminado com sucesso!")
            # Se viemos do artista, voltamos ao artista. Se não, vamos para a home.
            if artist_slug:
                return redirect('artist-detail', slug=artist_slug)
            return redirect('home')
        else:
            messages.error(request, "Erro ao eliminar o álbum.")
    return redirect('home')

def delete_track_view(request, slug):
    if request.method == "POST":
        artist_slug = request.POST.get("artist_slug")
        if sq.delete_track(slug):
            messages.success(request, "Faixa eliminada com sucesso!")
        else:
            messages.error(request, "Erro ao eliminar a faixa.")
        return redirect('artist-detail', slug=artist_slug)
    return redirect('home')