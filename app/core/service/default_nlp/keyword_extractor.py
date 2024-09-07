"""Provides a custom implementation of yake.KeywordExtractor."""

__all__ = ["CustomKeywordExtractor"]

from yake import KeywordExtractor


class CustomKeywordExtractor(KeywordExtractor):
    """Custom implementation of yake.KeywordExtractor"""

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        lan="en",
        n=3,
        dedupLim=0.9,
        dedupFunc="seqm",
        windowsSize=1,
        top=20,
        features=None,
        stopwords=None,
    ):
        super().__init__(
            lan, n, dedupLim, dedupFunc, windowsSize, top, features, stopwords
        )

        # Override stopword set to allow specified words.
        allowed_stopwords = ["course", "value"]
        self.stopword_set = [x for x in self.stopword_set if x not in allowed_stopwords]
