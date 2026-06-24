"""
music_graph/views.py
Django Server-Side Rendered Views adaptadas para o Fact Graph (TP1)
"""
from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse
from django.contrib import messages

from music_graph import sparql_queries as sq
from music_graph.rdf_store import store

import json

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
    """Página de pesquisa com filtros e opção de criar Artista."""
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

        # Se estamos a procurar artistas e escrevemos algo
        if entity_type in ['all', 'artist']:
            # Ponto 2 do Feedback: Usamos uma query ASK para verificar se existe exatamente
            if not sq.ask_artist_exists(q):
                can_create_artist = True

    context = {
        'query': q,
        'current_type': entity_type,
        'results': results,
        'total_count': total_count,
        'can_create_artist': can_create_artist, # Passamos esta flag para o HTML
    }
    return render(request, 'music_graph/search.html', context)


def stats_view(request):
    """Página de Estatísticas com Gráficos."""
    # Obter os dados do SPARQL
    top_genres_data = sq.get_top_genres_stats(10)
    energy_data = sq.get_avg_energy_by_genre(10)

    # Formatar para as listas que o Chart.js entende (separar Labels de Valores)
    context = {
        # Gráfico 1: Top Géneros
        'g1_labels': json.dumps([item["label"] for item in top_genres_data]),
        'g1_data': json.dumps([item["count"] for item in top_genres_data]),

        # Gráfico 2: Média de Energia
        'g2_labels': json.dumps([item["label"] for item in energy_data]),
        'g2_data': json.dumps([item["avg"] for item in energy_data]),
    }

    return render(request, 'music_graph/stats.html', context)

def artist_detail(request, slug):
    """Página de detalhes de um artista."""
    artist_data = sq.get_artist_detail(slug)
    if not artist_data:
        raise Http404("Artista não encontrado no Knowledge Graph.")

    context = {
        'artist': artist_data,
    }
    return render(request, 'music_graph/artist_detail.html', context)

def create_artist_view(request):
    if request.method == "POST":
        artist_name = request.POST.get("artist_name")
        if artist_name:
            # Dupla verificação de segurança com ASK
            if not sq.ask_artist_exists(artist_name):
                slug = sq.create_new_artist(artist_name)
                messages.success(request, f"Artista '{artist_name}' criado e adicionado ao Grafo!")
                return redirect('artist-detail', slug=slug)
            else:
                messages.warning(request, "Este artista já existe no sistema.")
    return redirect('search')


def add_track_view(request, slug):
    if request.method == "POST":
        track_name = request.POST.get("track_name")
        genre_name = request.POST.get("genre_name")
        energy = request.POST.get("energy", 0.5)
        album_slug = request.POST.get("album_slug")

        # O NOVO ASK EM AÇÃO!
        if sq.ask_track_exists(slug, track_name):
            messages.warning(request, f"A música '{track_name}' já existe neste artista!")
        else:
            if sq.add_new_track(slug, track_name, genre_name, float(energy), album_slug):
                messages.success(request, f"Faixa '{track_name}' criada com sucesso!")
            else:
                messages.error(request, "Erro ao criar a faixa.")

        if album_slug:
            return redirect('album-detail', slug=album_slug)
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
        album_slug = request.POST.get("album_slug")  # Para saber de onde viemos

        if sq.delete_track(slug):
            messages.success(request, "Faixa eliminada permanentemente do sistema!")
        else:
            messages.error(request, "Erro ao eliminar a faixa.")

        if album_slug:
            return redirect('album-detail', slug=album_slug)
        if artist_slug:
            return redirect('artist-detail', slug=artist_slug)
    return redirect('home')

def remove_track_from_album_view(request, album_slug, track_slug):
    if request.method == "POST":
        if sq.remove_track_from_album(track_slug, album_slug):
            messages.success(request, "Faixa retirada do álbum. Continua no sistema como Single.")
        else:
            messages.error(request, "Erro ao retirar faixa do álbum.")
    return redirect('album-detail', slug=album_slug)

def add_existing_track_view(request, album_slug):
    if request.method == "POST":
        track_slug = request.POST.get("track_slug")
        if track_slug and sq.add_existing_track_to_album(track_slug, album_slug):
            messages.success(request, "Faixa associada a este álbum com sucesso!")
        else:
            messages.error(request, "Erro ao associar a faixa.")
    return redirect('album-detail', slug=album_slug)


def edit_track_view(request, slug):
    if request.method == "POST":
        track_name = request.POST.get("track_name")
        genre_name = request.POST.get("genre_name")
        energy = request.POST.get("energy")
        artist_slug = request.POST.get("artist_slug")
        album_slug = request.POST.get("album_slug")

        if sq.update_track(slug, track_name, genre_name, float(energy)):
            messages.success(request, f"Faixa '{track_name}' atualizada!")
        else:
            messages.error(request, "Erro ao atualizar a faixa.")

        if album_slug:
            return redirect('album-detail', slug=album_slug)
        if artist_slug:
            return redirect('artist-detail', slug=artist_slug)
    return redirect('home')

def raw_artist_view(request, slug):
    """Retorna o resultado do DESCRIBE (para visualização no browser)."""
    rdf_data = sq.describe_artist(slug)
    # Mostramos como texto simples para se ver os triplos puros
    return HttpResponse(rdf_data, content_type="text/plain; charset=utf-8")

def export_artist_view(request, slug):
    """Retorna o resultado do CONSTRUCT como ficheiro de download."""
    rdf_data = sq.construct_artist_export(slug)
    response = HttpResponse(rdf_data, content_type="text/turtle; charset=utf-8")
    response['Content-Disposition'] = f'attachment; filename="artist_{slug}.ttl"'
    return response

