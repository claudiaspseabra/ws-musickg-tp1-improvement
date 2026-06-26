"""
music_graph/serializers.py
Django REST Framework serializers for local DB models only.
RDF data is returned as plain dicts directly from the KG.
"""
from rest_framework import serializers
from music_graph.models import SPARQLQueryTemplate, SearchLog

class SPARQLQueryTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for the SPARQLQueryTemplate model.
    Handles serialization of reusable SPARQL query metadata.
    """
    class Meta:
        model = SPARQLQueryTemplate
        fields = ['id', 'name', 'description', 'query_text',
                  'category', 'is_featured', 'created_at']

class SearchLogSerializer(serializers.ModelSerializer):
    """
    Serializer for the SearchLog model.
    Handles serialization of search activity logs and system metrics.
    """
    class Meta:
        model = SearchLog
        fields = ['id', 'query', 'results_count',
                  'entity_types_found', 'searched_at']