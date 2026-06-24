"""
music_graph/rdf_store.py

Camada de Persistência RDF (GraphDB HTTP)
Otimizada para o TP1: Factos Puros, Auto-Configuração e Upload Robusto em Streaming.
"""
import json
import logging
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

from rdflib import Namespace

# Namespaces (Apenas dados, sem ontologia formal)
BASE = Namespace("http://musickg.org/")
MUSIC = Namespace("http://musickg.org/data/")

log = logging.getLogger(__name__)

# Configurações do Servidor
GRAPHDB_URL = "http://localhost:7200"
GRAPHDB_REPOSITORY = "music-kg-tp1"
GRAPHDB_USER = "admin"
GRAPHDB_PASS = "root"

class _RDFStore:
    def __init__(self):
        self._stats: dict = {}
        self._loaded: bool = False
        self._use_graphdb: bool = False

        # Endpoints (resolvidos dinamicamente)
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
        Ponto de entrada no arranque do Django (AppConfig.ready).
        Tenta configurar e carregar os dados no GraphDB automaticamente.
        """
        if self._loaded: return

        if stats_path.exists():
            try:
                with open(stats_path, encoding="utf-8") as f:
                    self._stats = json.load(f)
            except Exception:
                pass

        log.info("A iniciar ligação ao GraphDB...")

        # Tenta ligar ao GraphDB com retries (para dar tempo ao Tomcat de arrancar)
        for attempt in range(3):
            if self._try_graphdb(nt_path):
                self._loaded = True
                return
            log.warning(f"GraphDB não respondeu (tentativa {attempt+1}/3). Aguardando 3s...")
            time.sleep(3)

        # Fallback Seguro: Em vez de bloquear o PC com rdflib, assume falha graciosa.
        log.error("CRÍTICO: GraphDB não está acessível. A aplicação irá correr sem dados.")
        self._loaded = True
        self._use_graphdb = False

    def _try_graphdb(self, nt_path: Path) -> bool:
        """Verifica se o repositório existe, cria-o se necessário e faz upload dos dados."""
        try:
            # 1. Ping ao servidor
            r = requests.get(f"{GRAPHDB_URL}/rest/repositories", timeout=5, headers={"Accept": "application/json"})
            if r.status_code != 200:
                return False

            # 2. Verifica/Cria repositório
            repos = [rep.get("id") for rep in r.json()]
            if GRAPHDB_REPOSITORY not in repos:
                log.info(f"Repositório '{GRAPHDB_REPOSITORY}' não existe. A criar (Ruleset: empty)...")
                if not self._create_repository():
                    return False
                time.sleep(2) # Espera que o repositório inicialize internamente

            # 3. Verifica dados e faz upload se estiver vazio
            count = self._graphdb_triple_count()
            if count < 500 and nt_path.exists():
                log.info(f"Repositório quase vazio ({count} triplos). A iniciar upload do ficheiro .nt...")
                if self._upload_nt(nt_path):
                    novo_count = self._graphdb_triple_count()
                    log.info(f"Upload concluído com sucesso! O Grafo tem agora {novo_count:,} triplos.")
                else:
                    log.error("Falha no upload automático.")
                    return False

            self._use_graphdb = True
            return True
        except requests.exceptions.ConnectionError:
            return False
        except Exception as e:
            log.warning(f"Erro na verificação do GraphDB: {e}")
            return False

    def _create_repository(self) -> bool:
        """Cria o repositório via API garantindo que o ruleset é 'empty' (Factos Puros)."""
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
            log.warning(f"Falha ao criar repositório: {e}")
            return False

    def _upload_nt(self, nt_path: Path) -> bool:
        """Upload em streaming via /statements (O método mais estável do GraphDB)."""
        try:
            with open(nt_path, 'rb') as f:
                # O parâmetro data=f faz com que a biblioteca requests envie o ficheiro
                # gradualmente, evitando estourar a memória RAM e evitando erros 10053.
                r = requests.post(
                    self._update_url,
                    data=f,
                    auth=(GRAPHDB_USER, GRAPHDB_PASS),
                    headers={'Content-Type': 'application/n-triples'},
                    timeout=300 # 5 minutos de timeout para garantir tempo de escrita no disco
                )

            if r.status_code in (200, 204):
                return True
            log.error(f"GraphDB rejeitou o ficheiro. Código: {r.status_code}. Info: {r.text[:100]}")
            return False
        except Exception as e:
            log.error(f"Erro na ligação de upload: {e}")
            return False

    def _graphdb_triple_count(self) -> int:
        q = "SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }"
        rows = self.execute_sparql(q)
        return int(rows[0].get("c", 0)) if rows else 0

    def execute_sparql(self, query_string: str) -> List[Dict[str, Any]]:
        """Executa uma query SELECT e retorna uma lista de dicionários puros."""
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
                log.warning(f"Erro SPARQL ({r.status_code}): {r.text[:100]}")
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
                        # Conversão simples de tipos básicos
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
            log.warning(f"Exceção SPARQL: {e}")
            return []

    def execute_sparql_update(self, update_string: str) -> bool:
        """Executa comandos INSERT / DELETE / UPDATE."""
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
            log.warning(f"Exceção SPARQL UPDATE: {e}")
            return False

    def get_stats(self) -> dict:
        stats = dict(self._stats)
        stats["backend"] = "GraphDB" if self._use_graphdb else "Desligado"
        stats["graphdb_url"] = GRAPHDB_URL
        stats["repository"] = GRAPHDB_REPOSITORY
        return stats

    def execute_ask(self, query_string: str) -> bool:
        """Executa uma query ASK e devolve True ou False."""
        if not self._use_graphdb:
            return False
        try:
            import requests
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
            log.warning(f"Exceção SPARQL ASK: {e}")
            return False

    def execute_graph_query(self, query_string: str, accept_format: str = "text/turtle") -> str:
        """Executa queries DESCRIBE ou CONSTRUCT e devolve a string no formato RDF."""
        if not self._use_graphdb:
            return ""
        try:
            import requests
            r = requests.post(
                self._sparql_url,
                data={"query": query_string},
                headers={"Accept": accept_format},
                timeout=15,
            )
            if r.status_code == 200:
                return r.text
            return f"# Erro SPARQL: {r.status_code}\n{r.text}"
        except Exception as e:
            return f"# Exceção de Rede: {e}"

# Singleton Instantiation
store = _RDFStore()