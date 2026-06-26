"""
convert_to_rdf.py
"""
import os
import logging
import pandas as pd
import argparse
from urllib.parse import quote
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import XSD

# Namespaces
BASE   = Namespace("http://musickg.org/")
MUSIC  = Namespace("http://musickg.org/data/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def safe_uri_part(text: str) -> str:
    """Transforms arbitrary alphanumeric entity strings into URL-safe components."""
    return quote(str(text).strip().replace(" ", "_"), safe="")

def load_and_clean(csv_path: str) -> pd.DataFrame:
    """Loads raw CSV data from storage, filters out unused structural columns, and enforces strict integrity constraints over critical resource identifiers."""
    log.info(f"Loading raw dataset from: {csv_path}...")

    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except FileNotFoundError:
        log.error(f"Target dataset file not found at: {csv_path}")
        raise

    cols_to_keep = [
        "track_id", "track_name", "track_artist", "track_popularity",
        "track_album_name", "track_album_release_date", "playlist_genre",
        "energy", "danceability", "valence", "tempo", "loudness"
    ]

    available_cols = [c for c in cols_to_keep if c in df.columns]
    df = df[available_cols]

    df = df.rename(columns={
        "track_artist": "artist_name",
        "track_album_name": "album_name",
        "playlist_genre": "genre"
    })
    return df.dropna(subset=["artist_name", "track_name", "track_id"])

def convert_to_rdf(df: pd.DataFrame):
    """Iterates through structured rows to materialize normalized statement assertions."""
    g = Graph()
    g.bind("music", MUSIC)

    log.info(f"Materializing semantic statements for {len(df):,} target rows...")

    for row in df.itertuples(index=False):
        a_uri   = BASE[f"artist/{safe_uri_part(row.artist_name)}"]
        t_uri   = BASE[f"track/{safe_uri_part(row.track_id)}"]
        g_uri   = BASE[f"genre/{safe_uri_part(row.genre)}"]
        alb_uri = BASE[f"album/{safe_uri_part(row.album_name)}"]

        g.add((t_uri, MUSIC.trackName, Literal(row.track_name)))
        g.add((t_uri, MUSIC.performedBy, a_uri))
        g.add((t_uri, MUSIC.inGenre, g_uri))
        g.add((t_uri, MUSIC.inAlbum, alb_uri))

        g.add((a_uri, MUSIC.artistName, Literal(row.artist_name)))
        g.add((g_uri, MUSIC.label, Literal(row.genre)))
        g.add((alb_uri, MUSIC.albumName, Literal(row.album_name)))

        release_date = str(row.track_album_release_date)
        if len(release_date) >= 4 and release_date[:4].isdigit():
            g.add((alb_uri, MUSIC.releaseYear, Literal(int(release_date[:4]), datatype=XSD.integer)))

        if pd.notna(row.track_popularity):
            g.add((t_uri, MUSIC.popularity, Literal(int(row.track_popularity), datatype=XSD.integer)))
        if pd.notna(row.energy):
            g.add((t_uri, MUSIC.energy, Literal(float(row.energy), datatype=XSD.float)))
        if pd.notna(row.danceability):
            g.add((t_uri, MUSIC.danceability, Literal(float(row.danceability), datatype=XSD.float)))
        if pd.notna(row.valence):
            g.add((t_uri, MUSIC.valence, Literal(float(row.valence), datatype=XSD.float)))
        if pd.notna(row.tempo):
            g.add((t_uri, MUSIC.tempo, Literal(float(row.tempo), datatype=XSD.float)))

    return g

def main(csv_path: str, data_dir: str) -> None:
    """Executes the pipeline and persists the resulting statements into an N-Triples graph file."""
    df = load_and_clean(csv_path)
    graph = convert_to_rdf(df)

    os.makedirs(data_dir, exist_ok=True)
    graph.serialize(destination=os.path.join(data_dir, "music_kg.nt"), format="nt")
    log.info("'music_kg.nt' file ready!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="spotify_songs.csv")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    main(args.csv, args.data_dir)
