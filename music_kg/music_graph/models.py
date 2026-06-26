"""
music_graph/models.py
Minimal Django database models for metadata and logging purposes.
Note: Primary domain data is persisted in the RDF Knowledge Graph (via rdf_store.py).
"""
from django.db import models


class SPARQLQueryTemplate(models.Model):
    """
    Stores reusable SPARQL query templates used for advanced analytics and data exploration within the application.
    """
    CATEGORY_CHOICES = [
        ('exploration', 'Exploration'),
        ('analysis',    'Analysis'),
        ('similarity',  'Similarity'),
        ('timeline',    'Timeline'),
    ]

    name        = models.CharField(max_length=200)
    description = models.TextField()
    query_text  = models.TextField()
    category    = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    is_featured = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_featured', 'name']

    def __str__(self):
        return f"[{self.category}] {self.name}"


class SearchLog(models.Model):
    """
    Logs user search queries to track activity and measure system performance.
    """
    query               = models.CharField(max_length=500)
    results_count       = models.IntegerField(default=0)
    entity_types_found  = models.JSONField(default=dict)
    searched_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-searched_at']

    def __str__(self):
        return f'"{self.query}" → {self.results_count} results'
