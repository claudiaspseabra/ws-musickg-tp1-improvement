"""
music_graph/rdf_store.py

RDF Persistence Layer (GraphDB HTTP)
"""
import json
import logging
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

from rdflib import Namespace

# Namespaces
BASE = Namespace("http://musickg.org/")
MUSIC = Namespace("http://musickg.org/data/")

log = logging.getLogger(__name__)

# Server Configuration
GRAPHDB_URL = "http://localhost:7200"
GRAPHDB_REPOSITORY = "music-kg-tp1"
GRAPHDB_USER = "admin"
GRAPHDB_PASS = "root"

class _RDFStore:
    def __init__(self):
        self._stats: dict = {}
        self._loaded: bool = False
        self._use_graphdb: bool = False

        self._sparql_url = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"
        self._update_url = f"{self._sparql_url}/statements"

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def using_graphdb(self) -> bool:
        return self._use_graphdb

    def load(self, nt_path: Path, stats_path: Path) -> None:
        """
        Initialization point during Django startup (AppConfig.ready).
        Attempts to automatically configure and load data into GraphDB.
        """
        if self._loaded: return

        if stats_path.exists():
            try:
                with open(stats_path, encoding="utf-8") as f:
                    self._stats = json.load(f)
            except Exception:
                pass

        log.info("Starting connection to GraphDB...")

        # Connection retries
        for attempt in range(3):
            if self._try_graphdb(nt_path):
                self._loaded = True
                return
            log.warning(f"GraphDB not responding (attempt {attempt+1}/3). Waiting 3s...")
            time.sleep(3)

        # Secure Fallback: app runs in read-only/disconnected mode
        log.error("CRITICAL: GraphDB unreachable. Application running in offline mode.")
        self._loaded = True
        self._use_graphdb = False

    def _try_graphdb(self, nt_path: Path) -> bool:
        """Checks repository existence, creates if necessary, and uploads data."""
        try:
            r = requests.get(f"{GRAPHDB_URL}/rest/repositories", timeout=5, headers={"Accept": "application/json"})
            if r.status_code != 200:
                return False

            repos = [rep.get("id") for rep in r.json()]
            if GRAPHDB_REPOSITORY not in repos:
                log.info(f"Repository '{GRAPHDB_REPOSITORY}' not found. Creating (Ruleset: empty)...")
                if not self._create_repository():
                    return False
                time.sleep(2)

            self._use_graphdb = True

            count = self._graphdb_triple_count()

            if count == 0 and nt_path.exists():
                log.info("Repository is empty. Starting initial data upload...")
                if self._upload_nt(nt_path):
                    new_count = self._graphdb_triple_count()
                    log.info(f"Upload complete! Inserted {new_count} triples.")
                else:
                    log.error("Automatic upload failed.")
                    return False
            else:
                log.info(f"GraphDB active with {count} triples. Skipping upload.")
            return True

        except requests.exceptions.ConnectionError:
            return False
        except Exception as e:
            log.warning(f"GraphDB verification error: {e}")
            return False

    def _create_repository(self) -> bool:
        """Creates a repository via API ('empty' ruleset)."""
        config = f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix rep: <http://www.openrdf.org/config/repository#> .
        @prefix sr: <http://www.openrdf.org/config/repository/sail#> .
        @prefix sail: <http://www.openrdf.org/config/sail#> .
        @prefix owlim: <http://www.ontotext.com/trree/owlim#> .
        [] a rep:Repository ;
           rep:repositoryID "{GRAPHDB_REPOSITORY}" ;
           rdfs:label "Music Knowledge Graph TP1" ;
           rep:repositoryImpl [
             rep:repositoryType "graphdb:SailRepository" ;
             sr:sailImpl [
               sail:sailType "graphdb:Sail" ;
               owlim:base-URL "http://musickg.org/" ;
               owlim:ruleset "empty" ;
               owlim:entity-index-size "10000000" ;
               owlim:cache-memory "256m" ;
               owlim:tuple-index-memory "256m" 
             ]
           ].
        """
        try:
            r = requests.post(
                f"{GRAPHDB_URL}/rest/repositories",
                data=config,
                headers={"Content-Type": "text/turtle"},
                auth=(GRAPHDB_USER, GRAPHDB_PASS),
                timeout=15,
            )
            return r.status_code in (200, 201)
        except Exception as e:
            log.warning(f"Failed to create repository: {e}")
            return False

    def _upload_nt(self, nt_path: Path) -> bool:
        """Streaming upload via /statements."""
        try:
            with open(nt_path, 'rb') as f:
                r = requests.post(
                    self._update_url,
                    data=f,
                    auth=(GRAPHDB_USER, GRAPHDB_PASS),
                    headers={'Content-Type': 'application/n-triples'},
                    timeout=300
                )

            if r.status_code in (200, 204):
                return True
            log.error(f"GraphDB rejected the file. Code: {r.status_code}. Info: {r.text[:100]}")
            return False
        except Exception as e:
            log.error(f"Upload connection error: {e}")
            return False

    def _graphdb_triple_count(self) -> int:
        q = "SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }"
        rows = self.execute_sparql(q)
        return int(rows[0].get("c", 0)) if rows else 0

    def execute_sparql(self, query_string: str) -> List[Dict[str, Any]]:
        """Executes a SELECT query and returns raw results as a dictionary list."""
        if not self._use_graphdb:
            return []
        try:
            r = requests.post(
                self._sparql_url,
                data={"query": query_string},
                headers={"Accept": "application/sparql-results+json"},
                timeout=45,
            )
            if r.status_code != 200:
                log.warning(f"SPARQL error ({r.status_code}): {r.text[:100]}")
                return []

            data = r.json()
            rows = []
            for binding in data["results"]["bindings"]:
                record = {}
                for var in data["head"]["vars"]:
                    node = binding.get(var)
                    if node:
                        val = node["value"]
                        typ = node.get("datatype", "")
                        if "integer" in typ or "int" in typ:
                            try: val = int(val)
                            except: pass
                        elif "decimal" in typ or "float" in typ or "double" in typ:
                            try: val = float(val)
                            except: pass
                        record[var] = val
                    else:
                        record[var] = None
                rows.append(record)
            return rows
        except Exception as e:
            log.warning(f"SPARQL exception: {e}")
            return []

    def execute_sparql_update(self, update_string: str) -> bool:
        """Executes INSERT / DELETE / UPDATE commands."""
        if not self._use_graphdb:
            return False
        try:
            r = requests.post(
                self._update_url,
                data={"update": update_string},
                auth=(GRAPHDB_USER, GRAPHDB_PASS),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            return r.status_code in (200, 204)
        except Exception as e:
            log.warning(f"SPARQL UPDATE exception: {e}")
            return False

    def get_stats(self) -> dict:
        stats = dict(self._stats)
        stats["backend"] = "GraphDB" if self._use_graphdb else "Disconnected"
        stats["graphdb_url"] = GRAPHDB_URL
        stats["repository"] = GRAPHDB_REPOSITORY
        return stats

    def execute_ask(self, query_string: str) -> bool:
        """Executes an ASK query and returns boolean result."""
        if not self._use_graphdb:
            return False
        try:
            r = requests.post(
                self._sparql_url,
                data={"query": query_string},
                headers={"Accept": "application/sparql-results+json"},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("boolean", False)
            return False
        except Exception as e:
            log.warning(f"SPARQL ASK exception: {e}")
            return False

    def execute_graph_query(self, query_string: str, accept_format: str = "text/turtle") -> str:
        """Executes DESCRIBE or CONSTRUCT queries and returns the RDF response."""
        if not self._use_graphdb:
            return ""
        try:
            r = requests.post(
                self._sparql_url,
                data={"query": query_string},
                headers={"Accept": accept_format},
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
            return f"# SPARQL Error: {r.status_code}\n{r.text}"
        except Exception as e:
            return f"# Network Exception: {e}"

# Singleton Instantiation
store = _RDFStore()
