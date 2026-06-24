"""
convert_to_rdf.py
Spotify Tracks Dataset → Music Knowledge Graph (Factos puros)
"""
import os
import logging
import pandas as pd
import argparse
from urllib.parse import quote
from rdflib import Graph, Literal, Namespace, RDF

# Namespaces (Vocabulário simples)
BASE   = Namespace("http://musickg.org/")
MUSIC  = Namespace("http://musickg.org/ontology#")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def safe_uri_part(text: str) -> str:
    return quote(str(text).strip().replace(" ", "_"), safe="")

def load_and_clean(csv_path: str) -> pd.DataFrame:
    log.info(f"Carregando {csv_path}...")
    df = pd.read_csv(csv_path, encoding="utf-8")
    df = df.rename(columns={
        "track_artist": "artist_name",
        "track_album_name": "album_name",
        "playlist_genre": "genre"
    })
    return df.dropna(subset=["artist_name", "track_name", "track_id"])

def convert_to_rdf(df: pd.DataFrame):
    g = Graph()
    g.bind("music", MUSIC)

    log.info(f"Gerando factos para {len(df):,} registos...")
    for row in df.itertuples(index=False):
        # URIs
        a_uri  = BASE[f"artist/{safe_uri_part(row.artist_name)}"]
        t_uri  = BASE[f"track/{safe_uri_part(row.track_id)}"]
        g_uri  = BASE[f"genre/{safe_uri_part(row.genre)}"]

        # Triplos (Factos puros)
        g.add((t_uri, MUSIC.trackName, Literal(row.track_name)))
        g.add((t_uri, MUSIC.performedBy, a_uri))
        g.add((t_uri, MUSIC.inGenre, g_uri))
        g.add((a_uri, MUSIC.artistName, Literal(row.artist_name)))
        g.add((g_uri, MUSIC.label, Literal(row.genre)))

    return g

def main(csv_path: str, data_dir: str) -> None:
    df = load_and_clean(csv_path)
    graph = convert_to_rdf(df)

    os.makedirs(data_dir, exist_ok=True)
    graph.serialize(destination=os.path.join(data_dir, "music_kg.nt"), format="nt")
    log.info("Ficheiro music_kg.nt gerado com sucesso!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="spotify_songs.csv")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    main(args.csv, args.data_dir)