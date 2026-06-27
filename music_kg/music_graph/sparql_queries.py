"""
music_graph/sparql_queries.py
"""
import re
import time
import logging
import uuid
from typing import Optional, List, Dict, Any
from urllib.parse import quote, unquote

from music_graph.rdf_store import store, BASE, MUSIC

log = logging.getLogger(__name__)

# Shared SPARQL prefix block
_PREFIXES = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX music: <http://musickg.org/data/>
PREFIX base:  <http://musickg.org/>
"""

def _slug(uri: str) -> str:
    """Extracts the last path segment of a URI as a URL-safe slug."""
    return uri.rstrip("/").split("/")[-1]

def _int(val):
    """Helper to round SPARQL numeric results."""
    try:
        return int(float(val)) if val is not None else 0
    except (TypeError, ValueError):
        return 0

def _round(val: Any, precision: int = 3) -> float:
    """Helper to standardize metric variables into normalized float points."""
    try:
        return round(float(val), precision) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
# READ OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_artists(search: Optional[str] = None, limit: int = 500, offset: int =0) -> List[Dict]:
    """Queries GraphDB for artists based on the music:artistName predicate."""
    limit_val = int(limit) if limit else 500

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
            "genres": []
        })
    return results

def get_artist_detail(artist: str) -> Optional[Dict]:
    """Retrieves comprehensive artist data including tracks, albums, and similarity."""
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

    # Tracks and genres
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
        for raw_g in genre_str.split(","):
            if raw_g.strip():
                g_clean = unquote(raw_g.replace("_", " ")).strip().title()
                genres_set.add(g_clean)

        top_tracks.append({
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": genre_str if genre_str else "No genre",
            "energy": str(r.get("trackEnergy", "0.5")),
        })

    # Albums
    album_q = _PREFIXES + f"""
        SELECT ?albumUri ?albumName ?year (COUNT(DISTINCT ?track) AS ?trackCount) WHERE {{
            ?albumUri music:albumName ?albumName .
            {{
                {artist_ref} music:hasAlbum ?albumUri .
            }}
            UNION
            {{
                ?track music:performedBy {artist_ref} ;
                       music:inAlbum ?albumUri .
            }}
            OPTIONAL {{ ?albumUri music:releaseYear ?year }}
            OPTIONAL {{ ?track music:inAlbum ?albumUri }}
        }}
        GROUP BY ?albumUri ?albumName ?year
        ORDER BY DESC(?year)
    """

    albums = [
        {
            "uri": str(r["albumUri"]), "slug": _slug(str(r["albumUri"])),
            "name": str(r["albumName"]), "year": r.get("year", "Unknown"),
            "track_count": r.get("trackCount", 0),
        } for r in store.execute_sparql(album_q)
    ]

    # Similar artists inference
    similar_q = _PREFIXES + f"""
    SELECT ?simUri ?simName (COUNT(DISTINCT ?track2) AS ?overlapCount)
    WHERE {{
        ?track1 music:performedBy {artist_ref} ;
                music:inGenre ?sharedGenre .

        ?track2 music:inGenre ?sharedGenre ;
                music:performedBy ?simUri .
        
        ?simUri music:artistName ?simName .

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

def get_tracks(search=None, limit=50, offset=0) -> List[Dict]:
    """Filters track instances using simple text constraint matching."""
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
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "artist": str(r.get("artistName", "")),
            "genre": str(r.get("genreLabel", "")),
        }
        for r in rows
    ]

def get_album_detail(album_slug: str) -> Optional[Dict]:
    """Retrieves comprehensive album data, ordering tracks by their track number."""
    safe_slug = quote(album_slug, safe="")
    album_ref = f"<http://musickg.org/album/{safe_slug}>"

    info_q = _PREFIXES + f"""
        SELECT ?name ?year ?artistUri ?artistName WHERE {{
            {album_ref} music:albumName ?name .
            OPTIONAL {{ {album_ref} music:releaseYear ?year . }}
            OPTIONAL {{
                {{ ?artistUri music:hasAlbum {album_ref} . }}
                UNION
                {{ ?track music:inAlbum {album_ref} ; music:performedBy ?artistUri . }}
                ?artistUri music:artistName ?artistName .
            }}
        }} LIMIT 1
        """
    info = store.execute_sparql(info_q)
    if not info:
        return None

    r0 = info[0]
    artist_uri = r0.get("artistUri", "")

    tracks_q = _PREFIXES + f"""
        SELECT ?trackUri ?trackName ?trackNumber
                (GROUP_CONCAT(DISTINCT ?rawLabel; SEPARATOR="|") AS ?genres) 
                (SAMPLE(?energy) AS ?trackEnergy)
        WHERE {{
            ?trackUri music:inAlbum {album_ref} ;
                      music:trackName ?trackName .
            OPTIONAL {{
                ?trackUri music:inGenre ?g .
                OPTIONAL {{ ?g music:label ?lbl . }}
                BIND(COALESCE(?lbl, REPLACE(STR(?g), "^.*/", "")) AS ?rawLabel)
            }}
            OPTIONAL {{ ?trackUri music:energy ?energy . }}
            OPTIONAL {{ ?trackUri music:trackNumber ?trackNumber . }}
        }}
        GROUP BY ?trackUri ?trackName ?trackNumber
        ORDER BY (IF(BOUND(?trackNumber), ?trackNumber, 999)) ?trackName
    """

    tracks = []
    for r in store.execute_sparql(tracks_q):
        raw_genres_str = str(r.get("genres", ""))
        track_genres = []
        if raw_genres_str:
            for item in raw_genres_str.split("|"):
                clean = unquote(item.replace("_", " ")).strip().title()
                if clean and clean.lower() != "none":
                    track_genres.append(clean)

        tracks.append({
            "uri": str(r["trackUri"]),
            "slug": _slug(str(r["trackUri"])),
            "name": str(r["trackName"]),
            "genre": ", ".join(sorted(list(set(track_genres)))) if track_genres else "No genre",
            "energy": str(r.get("trackEnergy", "0.5")),
            "track_number": str(r.get("trackNumber", ""))
        })

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
        "year": str(r0.get("year", "Unknown")),
        "artist_name": str(r0.get("artistName", "Various Artists")),
        "artist_slug": _slug(artist_uri) if artist_uri else "",
        "tracks": tracks,
        "other_tracks": other_tracks,
        "track_count": len(tracks)
    }

def full_text_search(query: str, entity_type: Optional[str] = None, limit: int = 50) -> dict:
    q_lower = query.strip().lower() if query else ""
    if not q_lower:
        return {"results": [], "total_count": 0}

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
# WRITE, UPDATE AND DELETE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def create_new_artist(artist_name: str) -> str:
    """Inserts a new artist in the graph."""
    safe_slug = quote(artist_name.lower().strip().replace(" ", "_"), safe="")
    a_uri = f"<http://musickg.org/artist/{safe_slug}>"

    query = _PREFIXES + f"""
    INSERT DATA {{
        {a_uri} music:artistName "{artist_name}" .
    }}
    """
    store.execute_sparql_update(query)
    return safe_slug

def delete_artist(artist_slug: str) -> bool:
    """Removes an artist and all tracks associated."""
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

def add_new_track(artist_slug: str, track_name: str, genre_name: str, energy: float, album_slug: str = None) -> bool:
    """Inserts a new track. Optionally links it to an album."""
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


def update_track(track_slug: str, track_name: str, genre_name: str, energy: float, track_number: str = "") -> bool:
    """Updates the name, genre, energy and track number of an existing track bulletproofly."""
    safe_slug = quote(track_slug, safe="")
    t_uri = f"<http://musickg.org/track/{safe_slug}>"

    delete_query = _PREFIXES + f"""
        DELETE {{
            {t_uri} music:trackName ?oldName .
            {t_uri} music:inGenre ?oldGenre .
            {t_uri} music:energy ?oldEnergy .
            {t_uri} music:trackNumber ?oldNum .
        }}
        WHERE {{
            {{ {t_uri} music:trackName ?oldName . }}
            UNION
            {{ {t_uri} music:inGenre ?oldGenre . }}
            UNION
            {{ {t_uri} music:energy ?oldEnergy . }}
            UNION
            {{ {t_uri} music:trackNumber ?oldNum . }}
        }}
    """
    store.execute_sparql_update(delete_query)

    insert_genre_triples = ""
    if genre_name and genre_name.strip():
        parts = [g.strip() for g in genre_name.split(",") if g.strip()]
        for p in parts:
            normalized = p.title()
            if normalized.lower() in ['r&b', 'edm']:
                normalized = normalized.upper()

            g_slug = quote(normalized.lower().replace(" ", "_"), safe="")
            g_uri = f"<http://musickg.org/genre/{g_slug}>"
            insert_genre_triples += f"{t_uri} music:inGenre {g_uri} . {g_uri} music:label '{normalized.replace("'", "\\'")}' . "

    track_num_triple = ""
    if track_number and str(track_number).strip().isdigit():
        track_num_triple = f'{t_uri} music:trackNumber "{int(track_number)}"^^xsd:integer .'

    insert_query = _PREFIXES + f"""
        INSERT DATA {{
            {t_uri} music:trackName "{track_name}" ;
                    music:energy "{energy}"^^xsd:float .
            {insert_genre_triples}
            {track_num_triple}
        }}
    """
    return store.execute_sparql_update(insert_query)

def delete_track(track_slug: str) -> bool:
    """Deletes a track."""
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

def create_new_album(artist_slug: str, album_name: str, release_year: int) -> str:
    """Creates an album linked to a specific artist."""
    clean_name = re.sub(r'[^\w\s]', '', album_name.lower().strip())

    safe_slug = quote(clean_name.replace(" ", "_"), safe="")

    alb_uri = f"<http://musickg.org/album/{safe_slug}>"
    a_uri = f"<http://musickg.org/artist/{quote(artist_slug, safe='')}>"

    safe_album_name = album_name.replace('"', '\\"')

    query = _PREFIXES + f"""
        INSERT DATA {{
            {alb_uri} rdf:type music:Album ;
                      music:albumName "{safe_album_name}" ;
                      music:releaseYear "{release_year}"^^xsd:integer .

            {a_uri} music:hasAlbum {alb_uri} .
        }}
        """
    store.execute_sparql_update(query)
    return safe_slug

def update_album(album_slug: str, new_name: str, new_year: int) -> bool:
    """Updates album name and release year."""
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
    """Deletes an album and unlinks all its references."""
    safe_slug = quote(album_slug, safe="")
    alb_uri = f"<http://musickg.org/album/{safe_slug}>"

    query = _PREFIXES + f"""
    DELETE {{
        {alb_uri} ?p ?o .
        ?s ?p2 {alb_uri} .
    }}
    WHERE {{
        {{ {alb_uri} ?p ?o . }}
        UNION
        {{ ?s ?p2 {alb_uri} . }}
    }}
    """
    return store.execute_sparql_update(query)

def add_existing_track_to_album(track_slug: str, album_slug: str) -> bool:
    """Links an existing track to an album."""
    t_uri = f"<http://musickg.org/track/{quote(track_slug, safe='')}>"
    a_uri = f"<http://musickg.org/album/{quote(album_slug, safe='')}>"

    query = _PREFIXES + f"""
    DELETE {{ {t_uri} music:inAlbum ?oldAlb }}
    INSERT {{ {t_uri} music:inAlbum {a_uri} }}
    WHERE {{ OPTIONAL {{ {t_uri} music:inAlbum ?oldAlb }} }}
    """
    return store.execute_sparql_update(query)

def remove_track_from_album(track_slug: str, album_slug: str) -> bool:
    """Removes track from album.."""
    t_uri = f"<http://musickg.org/track/{quote(track_slug, safe='')}>"
    a_uri = f"<http://musickg.org/album/{quote(album_slug, safe='')}>"

    query = _PREFIXES + f"DELETE DATA {{ {t_uri} music:inAlbum {a_uri} . }}"
    return store.execute_sparql_update(query)

# ─────────────────────────────────────────────────────────────────────────────
# ASK
# ─────────────────────────────────────────────────────────────────────────────

def ask_artist_exists(artist_name: str) -> bool:
    """Executes a ASK constraint validation to check artist naming conflicts."""
    safe_name = artist_name.replace('"', '\\"')

    query = _PREFIXES + f"""
    ASK {{
        ?a music:artistName ?name .
        FILTER(LCASE(STR(?name)) = LCASE("{safe_name}"))
    }}
    """
    return store.execute_ask(query)

def ask_track_exists(artist_slug: str, track_name: str) -> bool:
    """Checks uniqueness constraints for single tracks."""
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

def ask_album_exists(artist_slug: str, album_name: str) -> bool:
    """Executes a  ASK constraint to check if an album already exists for a specific artist."""
    safe_name = album_name.replace('"', '\\"')
    a_uri = f"<http://musickg.org/artist/{quote(artist_slug, safe='')}>"

    query = _PREFIXES + f"""
    ASK {{
        ?album music:albumName ?name .
        FILTER(LCASE(STR(?name)) = LCASE("{safe_name}"))

        {{ {a_uri} music:hasAlbum ?album . }}
        UNION
        {{ ?track music:inAlbum ?album ; music:performedBy {a_uri} . }}
    }}
    """
    return store.execute_ask(query)

# ─────────────────────────────────────────────────────────────────────────────
# DESCRIBE AND CONSTRUCT
# ─────────────────────────────────────────────────────────────────────────────

def describe_artist(slug: str) -> str:
    """Constructs a graph containing local node statements."""
    a_uri = f"<http://musickg.org/artist/{quote(slug, safe='')}>"
    query = _PREFIXES + f"DESCRIBE {a_uri}"
    return store.execute_graph_query(query)

def construct_artist_export(slug: str) -> str:
    """Constructs a smaller graph with artist and their albums and tracks."""
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
# ANALYTICS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_top_genres_stats(limit: int = 10) -> List[Dict]:
    """Returns genres with the most tracks in the graph."""
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

def get_avg_energy_by_genre(limit: int = 10) -> List[Dict]:
    """Returns tracks average energy grouped by genre."""
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
# RECOMMENDATION AND SIMILARITY
# ─────────────────────────────────────────────────────────────────────────────

def get_track_vibe_recommendations(track_slug: str) -> Optional[dict]:
    """Discovers context-similar tracks."""
    safe_slug = quote(track_slug, safe="")
    t_uri = f"<http://musickg.org/track/{safe_slug}>"

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

        FILTER(?simTrackUri != {t_uri})
        FILTER(ABS(?myEnergy - ?simEnergy) <= 0.1)
    }}
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
            "diff": _round(float(r["diff"]), 3)
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
# TIMELINE
# ─────────────────────────────────────────────────────────────────────────────

def get_global_timeline() -> Dict[str, List[Dict]]:
    """Groups albums sorted by year and decade."""
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


def get_paginated_timeline(decade: str = None, letter: str = None, offset: int = 0, limit: int = 25) -> list:
    """Fetches paginated albums filtered by decade and starting letter."""
    filters = ""

    if decade and str(decade).lower() not in ['none', 'all', '']:
        filters += f"FILTER(FLOOR(?year / 10) * 10 = {decade}) \n"

    if letter and str(letter).lower() not in ['none', 'all', '']:
        safe_letter = str(letter).lower().replace('"', '')
        filters += f'FILTER(STRSTARTS(LCASE(STR(?albumName)), "{safe_letter}")) \n'

    query = _PREFIXES + f"""
    SELECT ?albumUri ?albumName ?year ?artistName ?artistSlug (COUNT(?track) AS ?trackCount)
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
            "artist_name": str(r.get("artistName", "Various Artists")),
            "artist_slug": str(r.get("artistSlug", "")),
            "track_count": int(r.get("trackCount", 0))
        }
        for r in store.execute_sparql(query)
    ]

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC AUDIO EXPLORER
# ─────────────────────────────────────────────────────────────────────────────

def get_all_genres() -> list:
    """Retrieves a list of all unique genres present in the graph."""
    query = _PREFIXES + """
    SELECT DISTINCT ?genreLabel WHERE {
        ?track music:inGenre ?g .
        ?g music:label ?genreLabel .
    } ORDER BY ?genreLabel
    """
    return [str(r["genreLabel"]).title() for r in store.execute_sparql(query)]

def explore_audio(genre: str = "all", min_energy: float = 0.0, max_energy: float = 1.0, limit: int = 100) -> list:
    """Search track applying combined genre and energy filters."""
    genre_filter = ""
    if genre and genre != "all":
        safe_genre = genre.replace('"', '\\"')
        genre_filter = f'FILTER(LCASE(STR(?genreLabel)) = LCASE("{safe_genre}"))'

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
