from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boxboxbox.summariser.web_search import (
    DigestDeps,
    _MAX_SEARCHES_PER_DIGEST,
    search_f1_news,
)


def _make_ctx(deps: DigestDeps) -> MagicMock:
    """Create a minimal RunContext-like mock carrying *deps*."""
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _make_deps(
    tavily_api_key: str = "test-key",
    circuit_name: str = "Monza",
    session_name: str = "Race",
) -> DigestDeps:
    return DigestDeps(
        tavily_api_key=tavily_api_key,
        circuit_name=circuit_name,
        session_name=session_name,
    )


_TAVILY_RESPONSE = {
    "results": [
        {
            "title": "Verstappen wins at Monza",
            "url": "https://formula1.com/article1",
            "content": "Max Verstappen took a dominant victory.",
        },
        {
            "title": "Hamilton battles back",
            "url": "https://autosport.com/article2",
            "content": "Lewis Hamilton recovered from P9 to the podium.",
        },
    ]
}


class TestDigestDeps:
    def test_construction(self):
        deps = _make_deps()
        assert deps.tavily_api_key == "test-key"
        assert deps.circuit_name == "Monza"
        assert deps.session_name == "Race"
        assert deps._search_count == 0

    def test_search_count_starts_at_zero(self):
        deps = _make_deps()
        assert deps._search_count == 0


class TestSearchF1News:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value=_TAVILY_RESPONSE)
            MockClient.return_value = mock_instance

            result = await search_f1_news(ctx, "race winner")

        assert "Verstappen wins at Monza" in result
        assert "Hamilton battles back" in result
        assert "formula1.com" in result
        assert "autosport.com" in result
        assert deps._search_count == 1

    @pytest.mark.asyncio
    async def test_augments_query_with_session_context(self):
        deps = _make_deps(circuit_name="Silverstone", session_name="Qualifying")
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value={"results": []})
            MockClient.return_value = mock_instance

            await search_f1_news(ctx, "pole position")

        call_args = mock_instance.search.call_args
        assert "F1 Silverstone Qualifying pole position" in call_args.kwargs["query"]

    @pytest.mark.asyncio
    async def test_filters_to_authoritative_domains(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value={"results": []})
            MockClient.return_value = mock_instance

            await search_f1_news(ctx, "test")

        call_args = mock_instance.search.call_args
        domains = call_args.kwargs["include_domains"]
        assert "formula1.com" in domains
        assert "autosport.com" in domains
        assert "skysports.com" in domains

    @pytest.mark.asyncio
    async def test_rate_limits_after_max_searches(self):
        deps = _make_deps()
        deps._search_count = _MAX_SEARCHES_PER_DIGEST
        ctx = _make_ctx(deps)

        result = await search_f1_news(ctx, "anything")

        assert result == "Search limit reached for this digest."
        assert deps._search_count == _MAX_SEARCHES_PER_DIGEST  # not incremented

    @pytest.mark.asyncio
    async def test_increments_search_count(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value={"results": []})
            MockClient.return_value = mock_instance

            await search_f1_news(ctx, "q1")
            assert deps._search_count == 1

            await search_f1_news(ctx, "q2")
            assert deps._search_count == 2

    @pytest.mark.asyncio
    async def test_returns_no_results_on_empty_response(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value={"results": []})
            MockClient.return_value = mock_instance

            result = await search_f1_news(ctx, "obscure query")

        assert result == "No results found."

    @pytest.mark.asyncio
    async def test_returns_no_results_on_api_error(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(side_effect=RuntimeError("API timeout"))
            MockClient.return_value = mock_instance

            result = await search_f1_news(ctx, "some query")

        assert result == "No results found."
        assert deps._search_count == 1  # still incremented before the call

    @pytest.mark.asyncio
    async def test_uses_basic_search_depth(self):
        deps = _make_deps()
        ctx = _make_ctx(deps)

        with patch("tavily.AsyncTavilyClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.search = AsyncMock(return_value={"results": []})
            MockClient.return_value = mock_instance

            await search_f1_news(ctx, "test")

        call_args = mock_instance.search.call_args
        assert call_args.kwargs["search_depth"] == "basic"
        assert call_args.kwargs["max_results"] == 3
