"""
music_graph/timeline.py

Advanced Analytical Queries for Temporal Discovery.
"""
import logging
from typing import List, Dict
from music_graph.rdf_store import store
from music_graph.sparql_queries import _PREFIXES, _round

log = logging.getLogger(__name__)

def get_timeline_data(start_year: int = 1950, end_year: int = 2024) -> List[Dict]:
    """
    Retrieves global music aggregates per year, including track/artist counts, dominant genres, average audio metrics, and top tracks.
    """
    # 1. per-year aggregate metrics
    agg_q = _PREFIXES + f"""
    SELECT ?year
           (COUNT(DISTINCT ?track)  AS ?trackCount)
           (COUNT(DISTINCT ?artist) AS ?artistCount)
           (AVG(?energy)            AS ?avgEnergy)
           (AVG(?dance)             AS ?avgDance)
    WHERE {{
        ?track music:inAlbum ?album ;
               music:performedBy ?artist .
        ?album music:releaseYear ?year .
        
        OPTIONAL {{
            ?track music:energy ?energy ;
                   music:danceability ?dance .
        }}
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    GROUP BY ?year
    ORDER BY ?year
    """
    agg_rows = store.execute_sparql(agg_q)

    # 2. determine the most prevalent genre per year
    genre_q = _PREFIXES + f"""
    SELECT ?year ?genreLabel (COUNT(?track) AS ?cnt) WHERE {{
        ?track music:inAlbum ?album ;
               music:inGenre ?g .
        ?album music:releaseYear ?year .
        ?g rdfs:label ?genreLabel .
        
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    GROUP BY ?year ?genreLabel
    ORDER BY ?year DESC(?cnt)
    """
    genre_rows = store.execute_sparql(genre_q)

    # build top-genre map
    top_genre_map: Dict[int, str] = {}
    for r in genre_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y and y not in top_genre_map:
            top_genre_map[y] = str(r["genreLabel"]).title()

    # 3. extract the top 3 most popular tracks per year
    top_tracks_q = _PREFIXES + f"""
    SELECT ?year ?trackName ?artistName ?popularity WHERE {{
        ?track music:inAlbum ?album ;
               music:trackName ?trackName ;
               music:performedBy ?artist .
        ?album music:releaseYear ?year .
        ?artist music:artistName ?artistName .
        
        OPTIONAL {{ ?track music:popularity ?popularity }}
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    ORDER BY ?year DESC(?popularity)
    """
    track_rows = store.execute_sparql(top_tracks_q)

    top_tracks_map: Dict[int, list] = {}
    for r in track_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y is None:
            continue
        lst = top_tracks_map.setdefault(y, [])
        if len(lst) < 3:
            lst.append({
                "name":       str(r["trackName"]),
                "artist":     str(r["artistName"]),
                "popularity": int(float(r.get("popularity", 0))),
            })

    # 4. assemble the final unified data structure
    timeline = []
    for r in agg_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y is None:
            continue
        timeline.append({
            "year":             y,
            "track_count":      int(r.get("trackCount", 0)),
            "artist_count":     int(r.get("artistCount", 0)),
            "top_genre":        top_genre_map.get(y, "Unknown"),
            "avg_energy":       _round(r.get("avgEnergy")),
            "avg_danceability": _round(r.get("avgDance")),
            "top_tracks":       top_tracks_map.get(y, []),
        })
    return timeline

def get_genre_evolution(genre_name: str) -> List[Dict]:
    """
    Analyzes how a specific genre's audio signature (energy, danceability) evolved across decades.
    """
    safe_genre = genre_name.replace('"', '\\"').lower()

    query = _PREFIXES + f"""
    SELECT ?decade
           (COUNT(DISTINCT ?track)  AS ?trackCount)
           (AVG(?energy)            AS ?avgEnergy)
           (AVG(?dance)             AS ?avgDance)
           (AVG(?valence)           AS ?avgValence)
    WHERE {{
        ?track music:inGenre ?g ;
               music:inAlbum ?album .
        ?g rdfs:label ?genreLabel .
        ?album music:releaseYear ?year .
        
        BIND (FLOOR(?year / 10) * 10 AS ?decade)
        
        OPTIONAL {{
            ?track music:energy ?energy ;
                   music:danceability ?dance ;
                   music:valence ?valence .
        }}
        
        FILTER(LCASE(STR(?genreLabel)) = "{safe_genre}")
        FILTER (?year >= 1950 && ?year <= 2024)
    }}
    GROUP BY ?decade
    ORDER BY ?decade
    """

    rows = store.execute_sparql(query)
    return [
        {
            "decade":           int(r["decade"]) if r.get("decade") is not None else None,
            "track_count":      int(r.get("trackCount", 0)),
            "avg_energy":       _round(r.get("avgEnergy")),
            "avg_danceability": _round(r.get("avgDance")),
            "avg_valence":      _round(r.get("avgValence")),
        }
        for r in rows
        if r.get("decade") is not None
    ]
