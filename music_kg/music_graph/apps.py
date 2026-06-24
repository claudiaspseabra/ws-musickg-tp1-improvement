"""
music_graph/apps.py
"""
from django.apps import AppConfig

class MusicGraphConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'music_graph'
    verbose_name = 'Music Knowledge Graph'

    def ready(self):
        """
        Called once when Django finishes loading.
        Initializes the RDF singleton.
        """
        import sys
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return

        from django.conf import settings
        from music_graph.rdf_store import store

        # Inicia a ligação ao GraphDB
        store.load(
            nt_path=settings.RDF_NT_PATH,
            stats_path=settings.RDF_STATS_PATH,
        )