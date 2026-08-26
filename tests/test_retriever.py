from resume_agent.retriever import rank_bullets


def test_rank_bullets_prefers_matching_keywords(example_bank):
    ranked = rank_bullets(example_bank.experiences, ["MCP", "Slack", "Microsoft Graph"])
    # The IBM MCP-server bullet should be at the top.
    assert ranked[0].bullet.bullet_id == "bul-ibm-2"
    assert ranked[0].score >= 3


def test_rank_bullets_stable_ordering_on_ties(example_bank):
    # A keyword that matches nothing produces all-zero scores; ordering must be
    # by entry_id then bullet_id.
    ranked = rank_bullets(example_bank.experiences, ["totally-absent-keyword"])
    ids = [(r.entry.entry_id, r.bullet.bullet_id) for r in ranked]
    assert ids == sorted(ids)
