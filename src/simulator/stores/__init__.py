# Repository/store layer for EpisodeLogger (Candidate D, D014).
#
# Each store here owns exactly one table and is independently constructable
# and testable — RelationshipStore(conn) works standalone, with no other
# store required to exist. See state/DEFERRED_ITEMS.md D014 for the full
# specification (Artifacts 1-4).
