"""
templates/sparql_queries.py

All SPARQL-backed query functions optimized for the Flat Fact Graph.
"""
import re
import time
import logging
import uuid
from typing import Optional, List, Dict, Any
from urllib.parse import quote, unquote

from music_graph.rdf_store import store, BASE, MUSIC

log = logging.getLogger(__name__)

# Shared SPARQL prefix block - Updated to the new namespace
_PREFIXES = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX music: <http://musickg.org/data/>
PREFIX base:  <http://musickg.org/>
"""

def _slug(uri: str) -> str:
    """Extract last path segment of a URI as a URL-safe slug."""
    return uri.rstrip("/").split("/")[-1]

def _int(val):
    try:
        return int(float(val)) if val is not None else 0
    except (TypeError, ValueError):
        return 0

# ─────────────────────────────────────────────────────────────────────────────
# 1. get_artists
# ─────────────────────────────────────────────────────────────────────────────

def get_artists(search=None, limit=500, offset=0) -> List[Dict]:
    """
    Queries GraphDB for artists based on the presence of the `music:artistName` predicate.
    """
    limit_val = int(limit) if limit else 500

    # Inferimos que é um artista porque tem o predicado music:artistName
    query = _PREFIXES + f"""
    SELECT ?uri ?name 
    WHERE {{
        ?uri music:artistName ?name .
    }}
    ORDER BY ?name
    LIMIT {limit_val}
    OFFSET {offset}
    """

    rows = store.execute_sparql(query)
    results = []
    for r in rows:
        uri_str = str(r["uri"])
        name = str(r.get("name") or uri_str.split("/")[-1])
        slug = uri_str.split("/")[-1]

        results.append({
            "uri": uri_str,
            "name": name,
            "slug": slug,
            "type": "artist",
            "genres": [] # Simplificando: géneros não vêm listados diretamente no node do artista nesta versão
        })
    return results

# ─────────────────────────────────────────────────────────────────────────────
# 2. get_artist_detail
# ─────────────────────────────────────────────────────────────────────────────

def get_artist_detail(artist: str) -> Optional[Dict]:
    artist_slug = artist.strip()
    artist_ref = f"<http://musickg.org/artist/{artist_slug}>"

    # Basic info
    basic_q = _PREFIXES + f"""
    SELECT ?name WHERE {{
        {artist_ref} music:artistName ?name .
    }} LIMIT 1
    """
    basic = store.execute_sparql(basic_q)
    if not basic:
        return None

    name = str(basic[0]["name"])

    # Tracks performed by this artist and their genres
    tracks_q = _PREFIXES + f"""
        SELECT ?trackUri ?trackName (GROUP_CONCAT(DISTINCT ?genreLabel; SEPARATOR=", ") AS ?genres) (SAMPLE(?energy) AS ?trackEnergy)
        WHERE {{
            ?trackUri music:performedBy {artist_ref} ;
                      music:trackName ?trackName .
            OPTIONAL {{
                ?trackUri music:inGenre ?g .
                ?trackUri music:energy ?energy .
                ?g music:label ?genreLabel .
            }}
        }}
        GROUP BY ?trackUri ?trackName
        ORDER BY ?trackName
        """

    top_tracks = []
    genres_set = set()

    for r in store.execute_sparql(tracks_q):
        genre_str = str(r.get("genres", ""))
        # Alimentar os géneros do artista separando pela vírgula
        for g in genre_str.split(", "):
            if g.strip(): genres_set.add(g.strip())

        top_tracks.append({
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": genre_str if genre_str else "Sem género",
            "energy": str(r.get("trackEnergy", "0.5")),
        })

    album_q = _PREFIXES + f"""
        SELECT ?albumUri ?albumName ?year (COUNT(?track) AS ?trackCount) WHERE {{
            ?track music:performedBy {artist_ref} ;
                   music:inAlbum ?albumUri .
            ?albumUri music:albumName ?albumName .
            OPTIONAL {{ ?albumUri music:releaseYear ?year }}
        }}
        GROUP BY ?albumUri ?albumName ?year
        ORDER BY DESC(?year)
        """

    albums = [
        {
            "uri": str(r["albumUri"]),
            "slug": _slug(str(r["albumUri"])),
            "name": str(r["albumName"]),
            "year": r.get("year", "Desconhecido"),
            "track_count": r.get("trackCount", 0),
        }
        for r in store.execute_sparql(album_q)
    ]

    # Similar artists: Find artists who play tracks in the same genres
    # This is a key requirement to show you can infer relationships using pure SPARQL
    similar_q = _PREFIXES + f"""
    SELECT ?simUri ?simName (COUNT(DISTINCT ?track2) AS ?overlapCount)
    WHERE {{
        # Find genres of tracks by the current artist
        ?track1 music:performedBy {artist_ref} ;
                music:inGenre ?sharedGenre .

        # Find other tracks in those genres and their artists
        ?track2 music:inGenre ?sharedGenre ;
                music:performedBy ?simUri .
        
        ?simUri music:artistName ?simName .

        # Exclude the current artist
        FILTER(?simUri != {artist_ref})
    }} 
    GROUP BY ?simUri ?simName
    ORDER BY DESC(?overlapCount)
    LIMIT 10
    """

    similar = [
        {"uri": str(r["simUri"]), "slug": _slug(str(r["simUri"])), "name": str(r["simName"])}
        for r in store.execute_sparql(similar_q)
    ]

    return {
        "uri":             artist_ref.strip("<>"),
        "slug":            artist_slug,
        "name":            name,
        "genres":          list(genres_set),
        "top_tracks":      top_tracks,
        "albums":          albums,
        "similar_artists": similar,
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3. get_tracks
# ─────────────────────────────────────────────────────────────────────────────

def get_tracks(search=None, limit=50, offset=0) -> List[Dict]:
    filters = ""
    if search:
        safe = search.replace('"', '\\"')
        filters = f'FILTER (contains(lcase(str(?trackName)), lcase("{safe}")))'

    query = _PREFIXES + f"""
    SELECT ?trackUri ?trackName ?artistName ?genreLabel
    WHERE {{
        ?trackUri music:trackName ?trackName ;
                  music:performedBy ?artist ;
                  music:inGenre ?g .
        ?artist music:artistName ?artistName .
        ?g music:label ?genreLabel .
        
        {filters}
    }}
    ORDER BY ?trackName
    LIMIT {limit}
    OFFSET {offset}
    """

    rows = store.execute_sparql(query)
    return [
        {
            "uri":         str(r["trackUri"]),
            "slug":        _slug(str(r["trackUri"])),
            "name":        str(r["trackName"]),
            "artist":      str(r.get("artistName", "")),
            "genre":       str(r.get("genreLabel", "")),
        }
        for r in rows
    ]

# ─────────────────────────────────────────────────────────────────────────────
# 4. Search and Utility methods
# ─────────────────────────────────────────────────────────────────────────────
# (Removido build_search_index_async para manter simplicidade e delegar
# a pesquisa puramente no GraphDB via SPARQL)

def full_text_search(query: str, entity_type: str = None, limit: int = 50) -> dict:
    q_lower = query.strip().lower() if query else ""
    if not q_lower:
        return {"results": [], "total_count": 0}

    # Novo filtro dinâmico de tipo
    type_filter = ""
    if entity_type in ['artist', 'track', 'album']:
        type_filter = f'FILTER(?type = "{entity_type}")'

    graph_q = _PREFIXES + f"""
    SELECT DISTINCT ?uri ?name ?type ?slug WHERE {{
        {{ ?uri music:artistName ?name . BIND("artist" AS ?type) }}
        UNION 
        {{ ?uri music:trackName ?name . BIND("track" AS ?type) }}
        UNION 
        {{ ?uri music:albumName ?name . BIND("album" AS ?type) }}

        BIND(REPLACE(STR(?uri), "^.*[/#]", "") AS ?slug)
        FILTER(CONTAINS(LCASE(STR(?name)), "{q_lower}"))
        {type_filter}
    }} LIMIT {limit}
    """
    graph_rows = store.execute_sparql(graph_q)
    results = [{"type": str(r["type"]), "uri": str(r["uri"]), "slug": str(r["slug"]), "name": str(r["name"])} for r in
               graph_rows]

    return {"results": results, "total_count": len(results)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRUD OPERATIONS (WRITE/UPDATE/DELETE)
# ─────────────────────────────────────────────────────────────────────────────

def add_new_track(artist_slug: str, track_name: str, genre_name: str, energy: float, album_slug: str = None) -> bool:
    """CREATE: Insere nova faixa. Opcionalmente vincula-a a um álbum."""
    import uuid
    t_id = str(uuid.uuid4())[:8]
    t_uri = f"<http://musickg.org/track/{t_id}>"
    g_slug = quote(genre_name.lower().strip().replace(" ", "_"), safe="")
    g_uri = f"<http://musickg.org/genre/{g_slug}>"
    a_uri = f"<http://musickg.org/artist/{quote(artist_slug, safe='')}>"

    album_triple = ""
    if album_slug:
        alb_uri = f"<http://musickg.org/album/{quote(album_slug, safe='')}>"
        album_triple = f"{t_uri} music:inAlbum {alb_uri} ."

    query = _PREFIXES + f"""
    INSERT DATA {{
        {t_uri} music:trackName "{track_name}" ;
                music:performedBy {a_uri} ;
                music:inGenre {g_uri} ;
                music:energy "{energy}"^^xsd:float .
        {album_triple}
        {g_uri} music:label "{genre_name}" .
    }}
    """
    return store.execute_sparql_update(query)


def remove_track_from_album(track_slug: str, album_slug: str) -> bool:
    """REMOVE DO ÁLBUM: Apaga apenas a relação inAlbum. A faixa continua no sistema."""
    t_uri = f"<http://musickg.org/track/{quote(track_slug, safe='')}>"
    a_uri = f"<http://musickg.org/album/{quote(album_slug, safe='')}>"

    query = _PREFIXES + f"DELETE DATA {{ {t_uri} music:inAlbum {a_uri} . }}"
    return store.execute_sparql_update(query)


def add_existing_track_to_album(track_slug: str, album_slug: str) -> bool:
    """LIGA AO ÁLBUM: Associa uma faixa existente a este álbum (removendo de álbuns antigos)."""
    t_uri = f"<http://musickg.org/track/{quote(track_slug, safe='')}>"
    a_uri = f"<http://musickg.org/album/{quote(album_slug, safe='')}>"

    query = _PREFIXES + f"""
    DELETE {{ {t_uri} music:inAlbum ?oldAlb }}
    INSERT {{ {t_uri} music:inAlbum {a_uri} }}
    WHERE {{ OPTIONAL {{ {t_uri} music:inAlbum ?oldAlb }} }}
    """
    return store.execute_sparql_update(query)


def update_album_year(album_uri: str, new_year: int) -> bool:
    """UPDATE: Altera o ano de lançamento de um álbum existente."""
    alb_uri = f"<{album_uri}>"

    query = _PREFIXES + f"""
    DELETE {{ 
        {alb_uri} music:releaseYear ?oldYear . 
    }}
    INSERT {{ 
        {alb_uri} music:releaseYear "{new_year}"^^xsd:integer . 
    }}
    WHERE  {{ 
        OPTIONAL {{ {alb_uri} music:releaseYear ?oldYear . }}
    }}
    """
    return store.execute_sparql_update(query)


def delete_artist(artist_slug: str) -> bool:
    """DELETE: Remove um artista e TODAS as faixas associadas a ele."""
    safe_slug = quote(artist_slug, safe="")
    a_uri = f"<http://musickg.org/artist/{safe_slug}>"

    query = _PREFIXES + f"""
    DELETE {{
        {a_uri} ?p ?o .
        ?track ?tp ?to .
    }}
    WHERE {{
        {a_uri} ?p ?o .
        OPTIONAL {{
            ?track music:performedBy {a_uri} .
            ?track ?tp ?to .
        }}
    }}
    """
    return store.execute_sparql_update(query)


# ─────────────────────────────────────────────────────────────────────────────
# 6. ALBUM DETAILS & EXTRA CRUD (Álbuns e Faixas)
# ─────────────────────────────────────────────────────────────────────────────

def get_album_detail(album_slug: str) -> Optional[Dict]:
    safe_slug = quote(album_slug, safe="")
    album_ref = f"<http://musickg.org/album/{safe_slug}>"

    info_q = _PREFIXES + f"""
    SELECT ?name ?year ?artistUri ?artistName WHERE {{
        {album_ref} music:albumName ?name .
        OPTIONAL {{ {album_ref} music:releaseYear ?year . }}
        OPTIONAL {{
            ?track music:inAlbum {album_ref} ;
                   music:performedBy ?artistUri .
            ?artistUri music:artistName ?artistName .
        }}
    }} LIMIT 1
    """
    info = store.execute_sparql(info_q)
    if not info:
        return None

    r0 = info[0]
    artist_uri = r0.get("artistUri", "")

    # Músicas que pertencem a este álbum
    tracks_q = _PREFIXES + f"""
        SELECT ?trackUri ?trackName (GROUP_CONCAT(DISTINCT ?genreLabel; SEPARATOR=", ") AS ?genres) (SAMPLE(?energy) AS ?trackEnergy) WHERE {{
            ?trackUri music:inAlbum {album_ref} ;
                      music:trackName ?trackName .
            OPTIONAL {{
                ?trackUri music:inGenre ?g .
                ?trackUri music:energy ?energy .
                ?g music:label ?genreLabel .
            }}
        }}
        GROUP BY ?trackUri ?trackName
        ORDER BY ?trackName
        """

    tracks = [
        {
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": str(r.get("genres", "Sem género")),
            "energy": str(r.get("trackEnergy", "0.5")),
        }
        for r in store.execute_sparql(tracks_q)
    ]

    # Músicas do mesmo artista que NÃO estão neste álbum (para o Dropdown)
    other_tracks = []
    if artist_uri:
        other_tracks_q = _PREFIXES + f"""
        SELECT DISTINCT ?trackUri ?trackName WHERE {{
            ?trackUri music:performedBy <{artist_uri}> ;
                      music:trackName ?trackName .
            FILTER NOT EXISTS {{ ?trackUri music:inAlbum {album_ref} }}
        }} ORDER BY ?trackName
        """
        for r in store.execute_sparql(other_tracks_q):
            other_tracks.append({"slug": _slug(str(r["trackUri"])), "name": str(r["trackName"])})

    return {
        "uri": album_ref.strip("<>"),
        "slug": album_slug,
        "name": str(r0["name"]),
        "year": str(r0.get("year", "Desconhecido")),
        "artist_name": str(r0.get("artistName", "Vários Artistas")),
        "artist_slug": _slug(artist_uri) if artist_uri else "",
        "tracks": tracks,
        "other_tracks": other_tracks, # Passamos as outras faixas para o HTML!
        "track_count": len(tracks)
    }


def update_album(album_slug: str, new_name: str, new_year: int) -> bool:
    """UPDATE: Atualiza o nome e o ano do Álbum."""
    safe_slug = quote(album_slug, safe="")
    alb_uri = f"<http://musickg.org/album/{safe_slug}>"

    query = _PREFIXES + f"""
    DELETE {{ 
        {alb_uri} music:albumName ?oldName ; 
                  music:releaseYear ?oldYear . 
    }}
    INSERT {{ 
        {alb_uri} music:albumName "{new_name}" ; 
                  music:releaseYear "{new_year}"^^xsd:integer . 
    }}
    WHERE  {{ 
        OPTIONAL {{ {alb_uri} music:albumName ?oldName . }}
        OPTIONAL {{ {alb_uri} music:releaseYear ?oldYear . }}
    }}
    """
    return store.execute_sparql_update(query)


def delete_album(album_slug: str) -> bool:
    """DELETE: Apaga o álbum. As músicas perdem o vínculo ao álbum."""
    safe_slug = quote(album_slug, safe="")
    alb_uri = f"<http://musickg.org/album/{safe_slug}>"

    query = _PREFIXES + f"""
    DELETE {{
        {alb_uri} ?p ?o .
        ?track music:inAlbum {alb_uri} .
    }}
    WHERE {{
        {alb_uri} ?p ?o .
        OPTIONAL {{ ?track music:inAlbum {alb_uri} . }}
    }}
    """
    return store.execute_sparql_update(query)


def delete_track(track_slug: str) -> bool:
    """DELETE: Apaga uma música do Grafo completamente."""
    safe_slug = quote(track_slug, safe="")
    t_uri = f"<http://musickg.org/track/{safe_slug}>"

    query = _PREFIXES + f"""
    DELETE {{
        {t_uri} ?p ?o .
        ?s ?p2 {t_uri} .
    }}
    WHERE {{
        {t_uri} ?p ?o .
        OPTIONAL {{ ?s ?p2 {t_uri} . }}
    }}
    """
    return store.execute_sparql_update(query)


def update_track(track_slug: str, track_name: str, genre_name: str, energy: float) -> bool:
    """UPDATE: Altera o nome, género e energia de uma música existente."""
    safe_slug = quote(track_slug, safe="")
    t_uri = f"<http://musickg.org/track/{safe_slug}>"
    g_slug = quote(genre_name.lower().strip().replace(" ", "_"), safe="")
    new_g_uri = f"<http://musickg.org/genre/{g_slug}>"

    query = _PREFIXES + f"""
    DELETE {{
        {t_uri} music:trackName ?oldName ;
                music:inGenre ?oldGenre ;
                music:energy ?oldEnergy .
    }}
    INSERT {{
        {t_uri} music:trackName "{track_name}" ;
                music:inGenre {new_g_uri} ;
                music:energy "{energy}"^^xsd:float .
        {new_g_uri} music:label "{genre_name}" .
    }}
    WHERE {{
        OPTIONAL {{ {t_uri} music:trackName ?oldName . }}
        OPTIONAL {{ {t_uri} music:inGenre ?oldGenre . }}
        OPTIONAL {{ {t_uri} music:energy ?oldEnergy . }}
    }}
    """
    return store.execute_sparql_update(query)


# ─────────────────────────────────────────────────────────────────────────────
# 7. QUERIES DE VALIDAÇÃO (ASK) E CRIAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def ask_artist_exists(artist_name: str) -> bool:
    """ASK: Verifica se um artista já existe no Grafo (case-insensitive)."""
    # Escapar aspas para evitar quebras no SPARQL
    safe_name = artist_name.replace('"', '\\"')

    query = _PREFIXES + f"""
    ASK {{
        ?a music:artistName ?name .
        FILTER(LCASE(STR(?name)) = LCASE("{safe_name}"))
    }}
    """
    return store.execute_ask(query)


def ask_track_exists(artist_slug: str, track_name: str) -> bool:
    """ASK: Verifica se uma música com este nome já existe para este artista."""
    safe_name = track_name.replace('"', '\\"')
    a_uri = f"<http://musickg.org/artist/{quote(artist_slug, safe='')}>"

    query = _PREFIXES + f"""
    ASK {{
        ?track music:performedBy {a_uri} ;
               music:trackName ?name .
        FILTER(LCASE(STR(?name)) = LCASE("{safe_name}"))
    }}
    """
    return store.execute_ask(query)

def create_new_artist(artist_name: str) -> str:
    """CREATE: Insere um novo artista no Grafo."""
    safe_slug = quote(artist_name.lower().strip().replace(" ", "_"), safe="")
    a_uri = f"<http://musickg.org/artist/{safe_slug}>"

    query = _PREFIXES + f"""
    INSERT DATA {{
        {a_uri} music:artistName "{artist_name}" .
    }}
    """
    store.execute_sparql_update(query)
    return safe_slug

# ─────────────────────────────────────────────────────────────────────────────
# 8. GRAFOS BRUTOS (DESCRIBE E CONSTRUCT)
# ─────────────────────────────────────────────────────────────────────────────

def describe_artist(slug: str) -> str:
    """DESCRIBE: Obtém todos os triplos onde o artista é sujeito ou objeto."""
    a_uri = f"<http://musickg.org/artist/{quote(slug, safe='')}>"
    query = _PREFIXES + f"DESCRIBE {a_uri}"
    return store.execute_graph_query(query)

def construct_artist_export(slug: str) -> str:
    """CONSTRUCT: Cria um mini-grafo com o artista, os seus álbuns e as suas faixas."""
    a_uri = f"<http://musickg.org/artist/{quote(slug, safe='')}>"
    query = _PREFIXES + f"""
    CONSTRUCT {{
        {a_uri} ?p ?o .
        ?track music:performedBy {a_uri} ;
               music:trackName ?tName ;
               music:inGenre ?genre .
        ?album music:albumName ?albName .
        {a_uri} music:hasAlbum ?album .
    }}
    WHERE {{
        {a_uri} ?p ?o .
        OPTIONAL {{
            ?track music:performedBy {a_uri} ;
                   music:trackName ?tName ;
                   music:inGenre ?genre .
        }}
        OPTIONAL {{
            ?track music:performedBy {a_uri} ;
                   music:inAlbum ?album .
            ?album music:albumName ?albName .
        }}
    }}
    """
    return store.execute_graph_query(query)

# ─────────────────────────────────────────────────────────────────────────────
# 9. ESTATÍSTICAS E GRÁFICOS (AGREGAÇÃO SPARQL)
# ─────────────────────────────────────────────────────────────────────────────

def get_top_genres_stats(limit: int = 10) -> list:
    """Retorna os géneros com mais músicas no grafo."""
    query = _PREFIXES + f"""
    SELECT ?genreLabel (COUNT(?track) AS ?count) WHERE {{
        ?track music:inGenre ?g .
        ?g music:label ?genreLabel .
    }}
    GROUP BY ?genreLabel
    ORDER BY DESC(?count)
    LIMIT {limit}
    """
    return [
        {"label": str(r["genreLabel"]).title(), "count": int(r["count"])}
        for r in store.execute_sparql(query)
    ]

def get_avg_energy_by_genre(limit: int = 10) -> list:
    """Retorna a energia média das músicas agrupadas por género."""
    query = _PREFIXES + f"""
    SELECT ?genreLabel (AVG(?energy) AS ?avgEnergy) WHERE {{
        ?track music:inGenre ?g ;
               music:energy ?energy .
        ?g music:label ?genreLabel .
    }}
    GROUP BY ?genreLabel
    ORDER BY DESC(?avgEnergy)
    LIMIT {limit}
    """
    return [
        {"label": str(r["genreLabel"]).title(), "avg": float(r["avgEnergy"])}
        for r in store.execute_sparql(query)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 10. RECOMENDAÇÃO E SIMILARIDADE MATEMÁTICA
# ─────────────────────────────────────────────────────────────────────────────

def get_track_vibe_recommendations(track_slug: str) -> Optional[dict]:
    """Procura músicas com a mesma 'vibe' (mesmo género e energia semelhante)."""
    safe_slug = quote(track_slug, safe="")
    t_uri = f"<http://musickg.org/track/{safe_slug}>"

    # 1. Obter a informação da música base
    info_q = _PREFIXES + f"""
    SELECT ?name ?energy ?genreLabel ?artistName ?artistSlug WHERE {{
        {t_uri} music:trackName ?name ;
                music:energy ?energy ;
                music:performedBy ?a_uri ;
                music:inGenre ?g_uri .
        ?g_uri music:label ?genreLabel .
        ?a_uri music:artistName ?artistName .
        BIND(REPLACE(STR(?a_uri), "^.*[/#]", "") AS ?artistSlug)
    }} LIMIT 1
    """
    info_res = store.execute_sparql(info_q)
    if not info_res:
        return None

    base_track = info_res[0]

    # 2. Obter músicas semelhantes usando a função ABS() (Valor Absoluto)
    sim_q = _PREFIXES + f"""
    SELECT ?simTrackUri ?simTrackName ?simArtistName ?simArtistSlug ?simEnergy 
           (ABS(?myEnergy - ?simEnergy) AS ?diff) 
    WHERE {{
        {t_uri} music:inGenre ?g_uri ;
                music:energy ?myEnergy .

        ?simTrackUri music:inGenre ?g_uri ;
                     music:energy ?simEnergy ;
                     music:trackName ?simTrackName ;
                     music:performedBy ?simArtistUri .

        ?simArtistUri music:artistName ?simArtistName .
        BIND(REPLACE(STR(?simArtistUri), "^.*[/#]", "") AS ?simArtistSlug)

        # Não recomendar a própria música
        FILTER(?simTrackUri != {t_uri})

        # A diferença de energia tem de ser <= 0.1 (10%)
        FILTER(ABS(?myEnergy - ?simEnergy) <= 0.1)
    }}
    # Ordenar pelas mais parecidas (menor diferença primeiro)
    ORDER BY ASC(?diff)
    LIMIT 5
    """

    sim_tracks = [
        {
            "slug": _slug(str(r["simTrackUri"])),
            "name": str(r["simTrackName"]),
            "artist_name": str(r["simArtistName"]),
            "artist_slug": str(r["simArtistSlug"]),
            "energy": float(r["simEnergy"]),
            "diff": round(float(r["diff"]), 3)
        }
        for r in store.execute_sparql(sim_q)
    ]

    return {
        "slug": track_slug,
        "name": str(base_track["name"]),
        "energy": float(base_track["energy"]),
        "genre": str(base_track["genreLabel"]).title(),
        "artist_name": str(base_track["artistName"]),
        "artist_slug": str(base_track["artistSlug"]),
        "similar_tracks": sim_tracks
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. TIMELINE / DISCOGRAFIA (CRONOLOGIA)
# ─────────────────────────────────────────────────────────────────────────────

def get_global_timeline() -> dict:
    """Obtém todos os álbuns ordenados por ano e agrupados por década pelo SPARQL."""
    query = _PREFIXES + """
    SELECT ?albumUri ?albumName ?year ?artistName ?artistSlug
           (FLOOR(?year / 10) * 10 AS ?decade)
           (COUNT(?track) AS ?trackCount)
    WHERE {
        ?albumUri music:albumName ?albumName ;
                  music:releaseYear ?year .
        OPTIONAL {
            ?track music:inAlbum ?albumUri ;
                   music:performedBy ?a_uri .
            ?a_uri music:artistName ?artistName .
            BIND(REPLACE(STR(?a_uri), "^.*[/#]", "") AS ?artistSlug)
        }
    }
    GROUP BY ?albumUri ?albumName ?year ?artistName ?artistSlug
    ORDER BY DESC(?year) DESC(?trackCount)
    """

    # Vamos estruturar os dados num dicionário: { "2020": [album1, album2], "2010": [...] }
    timeline = {}

    for r in store.execute_sparql(query):
        decade = str(int(r["decade"]))
        if decade not in timeline:
            timeline[decade] = []

        timeline[decade].append({
            "slug": _slug(str(r["albumUri"])),
            "name": str(r["albumName"]),
            "year": int(r["year"]),
            "artist_name": str(r.get("artistName", "Vários Artistas")),
            "artist_slug": str(r.get("artistSlug", "")),
            "track_count": int(r["trackCount"])
        })

    return timeline


def get_paginated_timeline(decade=None, letter=None, offset=0, limit=25) -> list[dict[str, str | int]]:
    """Obtém álbuns filtrados por década, letra inicial e paginados."""

    filters = ""
    if decade:
        filters += f"FILTER(FLOOR(?year / 10) * 10 = {decade})"
    if letter:
        # Filtra álbuns que começam com a letra escolhida
        filters += f'FILTER(STRSTARTS(LCASE(?albumName), "{letter.lower()}"))'

    query = _PREFIXES + f"""
    SELECT ?albumUri ?albumName ?year ?artistName ?artistSlug ?trackCount
    WHERE {{
        ?albumUri music:albumName ?albumName ;
                  music:releaseYear ?year .
        {filters}
        OPTIONAL {{
            ?track music:inAlbum ?albumUri ;
                   music:performedBy ?a_uri .
            ?a_uri music:artistName ?artistName .
            BIND(REPLACE(STR(?a_uri), "^.*[/#]", "") AS ?artistSlug)
        }}
    }}
    GROUP BY ?albumUri ?albumName ?year ?artistName ?artistSlug
    ORDER BY ?albumName
    LIMIT {limit} OFFSET {offset}
    """

    return [
        {
            "slug": _slug(str(r["albumUri"])),
            "name": str(r["albumName"]),
            "year": int(r["year"]),
            "artist_name": str(r.get("artistName", "Vários Artistas")),
            "artist_slug": str(r.get("artistSlug", "")),
        }
        for r in store.execute_sparql(query)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 12. EXPLORADOR DE ÁUDIO (FILTROS DINÂMICOS)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_genres() -> list:
    """Obtém a lista de todos os géneros únicos presentes no grafo."""
    query = _PREFIXES + """
    SELECT DISTINCT ?genreLabel WHERE {
        ?track music:inGenre ?g .
        ?g music:label ?genreLabel .
    } ORDER BY ?genreLabel
    """
    return [str(r["genreLabel"]).title() for r in store.execute_sparql(query)]


def explore_audio(genre: str = "all", min_energy: float = 0.0, max_energy: float = 1.0, limit: int = 100) -> list:
    """Pesquisa faixas aplicando filtros combinados de género e energia."""

    # 1. Construir o filtro de género dinamicamente
    genre_filter = ""
    if genre and genre != "all":
        safe_genre = genre.replace('"', '\\"')
        genre_filter = f'FILTER(LCASE(STR(?genreLabel)) = LCASE("{safe_genre}"))'

    # 2. Query com múltiplos filtros
    query = _PREFIXES + f"""
    SELECT DISTINCT ?trackUri ?trackName ?artistName ?artistSlug ?genreLabel ?energy 
    WHERE {{
        ?trackUri music:trackName ?trackName ;
                  music:performedBy ?a_uri ;
                  music:inGenre ?g_uri ;
                  music:energy ?energy .

        ?a_uri music:artistName ?artistName .
        BIND(REPLACE(STR(?a_uri), "^.*[/#]", "") AS ?artistSlug)

        ?g_uri music:label ?genreLabel .

        {genre_filter}

        # Filtro Matemático Combinado
        FILTER(?energy >= {min_energy} && ?energy <= {max_energy})
    }}
    ORDER BY DESC(?energy)
    LIMIT {limit}
    """

    return [
        {
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "artist_name": str(r["artistName"]),
            "artist_slug": str(r["artistSlug"]),
            "genre": str(r["genreLabel"]).title(),
            "energy": float(r["energy"])
        }
        for r in store.execute_sparql(query)
    ]