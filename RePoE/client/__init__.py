"""Client acquisition: patch observation, fixed-source acquisition, drafts, index lookup and source envelopes.

Modules here read the patch endpoint, the CDN, archives or acquisition records; none decodes game data.
Keep this file free of imports: ``source_rebinding`` and ``version`` must load without the HTTP client.
"""
