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
    SELECT ?trackUri ?trackName ?genreLabel
    WHERE {{
        ?trackUri music:performedBy {artist_ref} ;
                  music:trackName ?trackName ;
                  music:inGenre ?g .
        ?g music:label ?genreLabel .
    }}
    ORDER BY ?trackName
    """

    top_tracks = []
    genres_set = set()

    for r in store.execute_sparql(tracks_q):
        genres_set.add(str(r.get("genreLabel", "")))
        t = {
            "uri":  str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": str(r.get("genreLabel", "")),
        }
        # Evitar duplicação visual de faixas se o GraphDB devolver múltiplos géneros para a mesma
        if t["uri"] not in [track["uri"] for track in top_tracks]:
             top_tracks.append(t)

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

def full_text_search(query: str, limit: int = 20) -> dict:
    q_lower = query.strip().lower() if query else ""
    if not q_lower:
        return {"results": [], "total_count": 0}

    # Procura em Artistas e Faixas simultaneamente
    graph_q = _PREFIXES + f"""
    SELECT DISTINCT ?uri ?name ?type ?slug WHERE {{
        {{
            ?uri music:artistName ?name . BIND("artist" AS ?type)
        }}
        UNION 
        {{
            ?uri music:trackName ?name . BIND("track" AS ?type)
        }}
        UNION
        {{
            ?uri music:albumName ?name . BIND("album" AS ?type)
        }}
        
        BIND(REPLACE(STR(?uri), "^.*[/#]", "") AS ?slug)
        FILTER(CONTAINS(LCASE(STR(?name)), "{q_lower}"))
    }} LIMIT {limit}
    """
    graph_rows = store.execute_sparql(graph_q)
    results = []

    for r in graph_rows:
        results.append({
            "type": str(r["type"]), "uri": str(r["uri"]),
            "slug": str(r["slug"]), "name": str(r["name"]),
        })

    return {"results": results, "total_count": len(results)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRUD OPERATIONS (WRITE/UPDATE/DELETE)
# ─────────────────────────────────────────────────────────────────────────────

def add_new_track(artist_uri: str, track_name: str, genre_name: str, energy: float) -> bool:
    """CREATE: Insere uma nova faixa completa com Audio Features."""
    # Gerar URIs únicos
    track_id = str(uuid.uuid4())[:8]
    track_uri = f"<http://musickg.org/track/{track_id}>"
    genre_slug = _slug(genre_name.lower())
    genre_uri = f"<http://musickg.org/genre/{genre_slug}>"
    a_uri = f"<{artist_uri}>"

    query = _PREFIXES + f"""
    INSERT DATA {{
        {track_uri} music:trackName "{track_name}" ;
                    music:performedBy {a_uri} ;
                    music:inGenre {genre_uri} ;
                    music:energy "{energy}"^^xsd:float .

        {genre_uri} music:label "{genre_name}" .
    }}
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
    """Lê os detalhes de um Álbum e as faixas que o compõem."""
    # Django descodifica a URL. Precisamos de voltar a codificar para o formato exato do GraphDB
    safe_slug = quote(album_slug, safe="")
    album_ref = f"<http://musickg.org/album/{safe_slug}>"

    # Info básica do Álbum e do Artista (inferido pelas faixas do álbum)
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
    SELECT DISTINCT ?trackUri ?trackName ?genreLabel WHERE {{
        ?trackUri music:inAlbum {album_ref} ;
                  music:trackName ?trackName ;
                  music:inGenre ?g .
        ?g music:label ?genreLabel .
    }}
    ORDER BY ?trackName
    """

    tracks = [
        {
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": str(r.get("genreLabel", "")),
        }
        for r in store.execute_sparql(tracks_q)
    ]

    return {
        "uri": album_ref.strip("<>"),
        "slug": album_slug,  # Retornamos o original para o Django
        "name": str(r0["name"]),
        "year": str(r0.get("year", "Desconhecido")),
        "artist_name": str(r0.get("artistName", "Vários Artistas")),
        "artist_slug": _slug(artist_uri) if artist_uri else "",
        "tracks": tracks,
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