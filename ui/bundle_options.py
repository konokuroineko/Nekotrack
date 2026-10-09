"""Shared metadata for NekoTrack's automatic bundle options."""

BUNDLE_OPTION_GROUPS = (
    (
        "ANIME EXTRAS",
        (
            (
                "bundle_include_movies",
                "Movies",
                "Related films, movie arcs, and follow-up movies.",
            ),
            (
                "bundle_include_ovas",
                "OVAs",
                "Direct-to-video side stories and bonus episodes.",
            ),
            (
                "bundle_include_onas",
                "ONAs / web anime",
                "Web-released anime and shorts, including related entries like Break Time.",
            ),
            (
                "bundle_include_specials",
                "Specials",
                "Standalone or TV specials connected to the same series.",
            ),
        ),
    ),
    (
        "MANGA & LITERATURE",
        (
            (
                "bundle_include_manga",
                "Manga",
                "Related manga sequels and continuation entries.",
            ),
            (
                "bundle_include_novels",
                "Light novels",
                "Related light-novel entries in the same series.",
            ),
            (
                "bundle_include_one_shots",
                "One-shots",
                "Related one-shot manga entries.",
            ),
        ),
    ),
)

BUNDLE_OPTION_KEYS = tuple(
    key
    for _group_title, options in BUNDLE_OPTION_GROUPS
    for key, _label, _description in options
)
