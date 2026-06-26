"""
music_graph/apps.py
"""
from django.apps import AppConfig


class MusicGraphConfig(AppConfig):
    """
    Configuration for the Music Graph application.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'music_graph'
    verbose_name = 'Music Knowledge Graph'

    def ready(self):
        """
        Executed once when Django completes the initialization process.
        Initializes the RDF storage singleton.
        """
        import sys

        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return

        from django.conf import settings
        from music_graph.rdf_store import store

        store.load(
            nt_path=settings.RDF_NT_PATH,
            stats_path=settings.RDF_STATS_PATH,
        )
