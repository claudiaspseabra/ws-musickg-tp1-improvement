"""
music_graph/views.py
Django Server-Side Rendered Views para o TP1.
"""
from django.shortcuts import render
from django.http import Http404

from music_graph import sparql_queries as sq
from music_graph.rdf_store import store

def home(request):
    """Página inicial com as estatísticas do Knowledge Graph."""
    stats = store.get_stats()
    context = {
        'stats': stats,
    }
    return render(request, 'music_graph/home.html', context)

def search(request):
    """Página de pesquisa que processa os parâmetros do GET."""
    q = request.GET.get('q', '').strip()
    genre = request.GET.get('genre', '').strip()

    results = []
    total_count = 0

    if q or genre:
        # Reutilizamos a tua função de pesquisa já existente
        search_data = sq.full_text_search(q, genre=genre or None, limit=50)
        results = search_data.get("results", [])
        total_count = search_data.get("total_count", 0)

    context = {
        'query': q,
        'genre': genre,
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