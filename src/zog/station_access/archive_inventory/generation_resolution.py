from .models import Entry


def resolve_generation(generation):
    """Resolve one generation identity to one distinct observed rootfs digest."""
    if not generation:
        return {
            "state": "unknown",
            "digest": None,
            "observation": None,
            "candidate_count": 0,
        }

    query = Entry.objects.select_related("observation").filter(
        observation__complete=True,
        observation__status="ok",
        metadata__kind="root-filesystem",
        metadata__version=generation,
    )
    digests = list(query.order_by().values_list("digest", flat=True).distinct()[:2])
    if not digests:
        return {
            "state": "unresolved",
            "digest": None,
            "observation": None,
            "candidate_count": 0,
        }
    if len(digests) > 1:
        return {
            "state": "conflict",
            "digest": None,
            "observation": None,
            "candidate_count": query.order_by().values("digest").distinct().count(),
        }

    row = query.filter(digest=digests[0]).order_by(
        "-observation__observed_at",
        "-observation__received_at",
    ).first()
    return {
        "state": "resolved",
        "digest": row.digest,
        "observation": {
            "mirror": str(row.observation.host_id),
            "snapshot": str(row.observation_id),
            "collection": row.collection,
            "digest": row.digest,
            "observed_at": row.observation.observed_at.isoformat(),
        },
        "candidate_count": 1,
    }
