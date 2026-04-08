from django.apps import AppConfig


class AgentsGisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agents_gis"

    def ready(self):
        from . import tools_spatial  # noqa
        from . import tools_query  # noqa
        from . import tools_nearby  # noqa
        from . import tools_intersects  # noqa
        from . import tools_context  # noqa
        from . import tools_network_trace # noqa
        from . import tools_aggregate  # noqa
        from . import tools_buffer     # noqa
        from . import tools_dissolve        # noqa
        from . import tools_centroid        # noqa
        from . import tools_count_within    # noqa
        from . import tools_spatial_join    # noqa
        from . import tools_clip            # noqa
        from . import tools_grid_stats      # noqa
        from . import tools_difference      # noqa
        from . import tools_cluster_dbscan  # noqa
        from . import tools_convex_hull      # noqa
        from . import tools_voronoi          # noqa
        from . import tools_measure          # noqa
        from . import tools_overlay          # noqa
        from . import tools_nearest_neighbor # noqa
        from . import tools_within_distance  # noqa
        from . import tools_topology_check   # noqa