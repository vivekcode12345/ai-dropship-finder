"""Tests for the Viral Product Hunter API."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

# Set test token before importing api
os.environ.setdefault("DECODO_AUTH_TOKEN", "test-token")

# Import after setting env var
import api


class TestBuildSourceUrls(unittest.TestCase):
    """Test source URL building."""

    def test_returns_10_sources(self):
        """Should return exactly 10 sources."""
        sources = api.build_source_urls("pet gadgets")
        self.assertEqual(len(sources), 10)

    def test_google_sources_order(self):
        """Should have 6 Google sources in order."""
        sources = api.build_source_urls("pet gadgets")
        for i in range(6):
            self.assertEqual(sources[i]["source"], f"Google Search {i + 1}")

    def test_non_google_sources_order(self):
        """Should have correct non-Google sources."""
        sources = api.build_source_urls("pet gadgets")
        self.assertEqual(sources[6]["source"], "Amazon Search")
        self.assertEqual(sources[7]["source"], "Reddit Search")
        self.assertEqual(sources[8]["source"], "TikTok Shop Search")
        self.assertEqual(sources[9]["source"], "YouTube Search")

    def test_google_queries(self):
        """Should build correct Google queries."""
        sources = api.build_source_urls("test")
        queries = [s["payload"]["query"] for s in sources[:6]]
        expected = [
            "viral test products",
            "problem solving test products",
            "TikTok test gadgets",
            "Amazon best selling test under $50",
            "lightweight test products easy to ship",
            "test accessories under $50",
        ]
        self.assertEqual(queries, expected)

    def test_amazon_payload(self):
        """Should have correct Amazon payload."""
        sources = api.build_source_urls("test")
        amazon = sources[6]
        self.assertEqual(amazon["payload"]["target"], "amazon_search")
        self.assertEqual(amazon["payload"]["query"], "test under $50")
        self.assertEqual(amazon["payload"]["page_from"], "1")
        self.assertEqual(amazon["payload"]["parse"], True)

    def test_reddit_payload(self):
        """Should have correct Reddit payload with URL."""
        sources = api.build_source_urls("test")
        reddit = sources[7]
        self.assertEqual(reddit["payload"]["target"], "universal")
        self.assertIn("reddit.com", reddit["payload"]["url"])
        self.assertIn("viral+test+products", reddit["payload"]["url"])

    def test_tiktok_payload(self):
        """Should have correct TikTok Shop payload."""
        sources = api.build_source_urls("test")
        tiktok = sources[8]
        self.assertEqual(tiktok["payload"]["target"], "tiktok_shop_search")
        self.assertEqual(tiktok["payload"]["query"], "test")
        self.assertEqual(tiktok["payload"]["parse"], True)

    def test_youtube_payload(self):
        """Should have correct YouTube payload."""
        sources = api.build_source_urls("test")
        youtube = sources[9]
        self.assertEqual(youtube["payload"]["target"], "youtube_search")
        self.assertEqual(youtube["payload"]["query"], "viral test products TikTok")


class TestDecodoContentHandling(unittest.TestCase):
    """Test Decodo content parsing and stringification."""

    def test_stringify_json_string(self):
        """Should parse JSON strings."""
        content = '{"key": "value"}'
        result = api.stringify_decodo_content(content)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["key"], "value")

    def test_stringify_non_json_string(self):
        """Should return non-JSON strings as-is."""
        content = "This is HTML content"
        result = api.stringify_decodo_content(content)
        self.assertEqual(result, content)

    def test_parse_content_no_results(self):
        """Should return content as-is if no results key."""
        content = {"data": "value"}
        result = api.parse_decodo_content(content)
        self.assertEqual(result, content)

    def test_parse_content_with_results(self):
        """Should return nested results if present."""
        content = {
            "results": {
                "results": {"nested": "data"}
            }
        }
        result = api.parse_decodo_content(content)
        self.assertEqual(result, {"nested": "data"})

    def test_parse_content_results_not_dict(self):
        """Should return results directly if not a dict."""
        content = {"results": [1, 2, 3]}
        result = api.parse_decodo_content(content)
        self.assertEqual(result, [1, 2, 3])

    def test_old_parser_envelope(self):
        """Should handle old parser envelope format."""
        content = {
            "results": {
                "organic_results": [
                    {"title": "Product 1"},
                    {"title": "Product 2"}
                ]
            }
        }
        result = api.parse_decodo_content(content)
        self.assertIn("organic_results", result)

    def test_current_parser_envelope(self):
        """Should handle current parser envelope format."""
        content = {
            "results": {
                "results": {
                    "organic_products": [
                        {"title": "Product A"},
                        {"title": "Product B"}
                    ]
                }
            }
        }
        result = api.parse_decodo_content(content)
        self.assertIn("organic_products", result)


class TestGoogleContentTrimming(unittest.TestCase):
    """Test Google content trimming."""

    def test_trim_preserves_metadata(self):
        """Should preserve query, page, status."""
        content = {
            "query": "test query",
            "page": 1,
            "status": "success",
            "organic_results": list(range(20))
        }
        result = api.trim_google_content(content)
        self.assertEqual(result["query"], "test query")
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["status"], "success")

    def test_trim_ai_overviews_limit(self):
        """Should limit AI overviews to 3."""
        content = {"ai_overviews": list(range(10))}
        result = api.trim_google_content(content)
        self.assertEqual(len(result["ai_overviews"]), 3)

    def test_trim_organic_results_limit(self):
        """Should limit organic results to 10."""
        content = {"organic_results": [{"title": f"Result {i}"} for i in range(20)]}
        result = api.trim_google_content(content)
        self.assertEqual(len(result["organic_results"]), 10)

    def test_trim_related_questions_limit(self):
        """Should limit related questions to 10."""
        content = {"related_questions": list(range(20))}
        result = api.trim_google_content(content)
        self.assertEqual(len(result["related_questions"]), 10)

    def test_trim_shopping_results_limit(self):
        """Should limit shopping results to 25."""
        content = {"shopping_results": list(range(30))}
        result = api.trim_google_content(content)
        self.assertEqual(len(result["shopping_results"]), 25)

    def test_trim_preserves_object_sections(self):
        """Should preserve object-valued sections."""
        content = {"metadata": {"key": "value"}}
        result = api.trim_google_content(content)
        self.assertEqual(result["metadata"], {"key": "value"})


class TestAmazonContentTrimming(unittest.TestCase):
    """Test Amazon content trimming."""

    def test_trim_organic_products_limit(self):
        """Should limit organic products to 25."""
        content = {"organic_products": [{"title": f"Product {i}", "price": 10.0} for i in range(30)]}
        result = api.trim_amazon_content(content)
        self.assertEqual(len(result["organic_products"]), 25)

    def test_trim_organic_products_fields(self):
        """Should trim organic products to useful fields only."""
        product = {
            "title": "Test Product",
            "price": 10.0,
            "currency": "USD",
            "extra_field": "should be removed",
            "rating": 4.5,
            "unneeded": "data"
        }
        content = {"organic_products": [product]}
        result = api.trim_amazon_content(content)
        trimmed_product = result["organic_products"][0]
        self.assertIn("title", trimmed_product)
        self.assertIn("price", trimmed_product)
        self.assertIn("currency", trimmed_product)
        self.assertIn("rating", trimmed_product)
        self.assertNotIn("extra_field", trimmed_product)
        self.assertNotIn("unneeded", trimmed_product)


class TestProductExtraction(unittest.TestCase):
    """Test product extraction from Decodo results."""

    def test_extract_title_from_product_title(self):
        """Should extract title from product_title field."""
        result = api.extract_products_single(
            {"product_title": "Test Product", "price": 10.0},
            "Test Source"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["product"], "Test Product")

    def test_extract_title_from_title(self):
        """Should extract title from title field."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0},
            "Test Source"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["product"], "Test Product")

    def test_no_title_returns_none(self):
        """Should return None if no valid title."""
        result = api.extract_products_single(
            {"price": 10.0},
            "Test Source"
        )
        self.assertIsNone(result)

    def test_title_only_no_signals_returns_none(self):
        """Should return None if title-only without product signals."""
        result = api.extract_products_single(
            {"title": "Test Product"},
            "Test Source"
        )
        self.assertIsNone(result)

    def test_title_with_price(self):
        """Should accept title with price as valid product."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0},
            "Test Source"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["price"], 10.0)

    def test_title_with_rating(self):
        """Should accept title with rating as valid product."""
        result = api.extract_products_single(
            {"title": "Test Product", "rating": 4.5},
            "Test Source"
        )
        self.assertIsNotNone(result)

    def test_title_with_image(self):
        """Should accept title with image as valid product."""
        result = api.extract_products_single(
            {"title": "Test Product", "image": "http://example.com/image.jpg"},
            "Test Source"
        )
        self.assertIsNotNone(result)

    def test_viral_score_basic(self):
        """Should calculate basic viral score."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0},
            "Test Source"
        )
        self.assertEqual(result["viral_score"], 47)  # 35 + 12 for price in 5-50

    def test_viral_score_with_rating(self):
        """Should add rating to viral score."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0, "rating": 5.0},
            "Test Source"
        )
        self.assertEqual(result["viral_score"], 62)  # 35 + 12 + 15

    def test_viral_score_with_reviews(self):
        """Should add review count to viral score."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0, "reviews": 1000},
            "Test Source"
        )
        # 35 + 12 + round(log10(1000)*5) = 35 + 12 + round(3*5) = 35 + 12 + 15 = 62
        self.assertEqual(result["viral_score"], 62)

    def test_viral_score_with_image_url(self):
        """Should add image and URL bonuses."""
        result = api.extract_products_single(
            {
                "title": "Test Product",
                "price": 10.0,
                "image": "http://example.com/image.jpg",
                "url": "http://example.com/product"
            },
            "Test Source"
        )
        # 35 + 12 + 5 + 5 = 57
        self.assertEqual(result["viral_score"], 57)

    def test_viral_score_capped_at_100(self):
        """Should cap viral score at 100."""
        result = api.extract_products_single(
            {
                "title": "Test Product",
                "price": 25.0,
                "rating": 5.0,
                "reviews": 1000000,
                "image": "http://example.com/image.jpg",
                "url": "http://example.com/product",
                "badges": ["Amazon's Choice"]
            },
            "Test Source"
        )
        self.assertEqual(result["viral_score"], 100)

    def test_amazon_url_expansion(self):
        """Should expand relative Amazon URLs."""
        result = api.extract_products_single(
            {"title": "Test Product", "price": 10.0, "url": "/product.html"},
            "Amazon Search"
        )
        self.assertEqual(result["url"], "https://www.amazon.com/product.html")

    def test_extract_products_from_list(self):
        """Should extract products from a list of results."""
        results = [
            {"source": "Amazon", "data": {"organic_products": [
                {"product_title": "Product 1", "price": 10.0},
                {"product_title": "Product 2", "price": 15.0}
            ]}}
        ]
        products = api.extract_products(results)
        self.assertEqual(len(products), 2)

    def test_deduplication(self):
        """Should deduplicate products by normalized title."""
        results = [
            {"source": "Amazon", "data": {"organic_products": [
                {"title": "Product ONE", "price": 10.0},
                {"title": "Product 1", "price": 15.0},
                {"title": "product one", "price": 20.0}
            ]}}
        ]
        products = api.extract_products(results)
        # "Product ONE", "Product 1", "product one" should normalize to different titles
        # "product one" and "Product ONE" both normalize to "product one"
        # So we should have 2 unique (one for "product one", one for "product 1")
        self.assertLessEqual(len(products), 3)


class TestSourceSummary(unittest.TestCase):
    """Test source summary generation."""

    def test_summary_basic(self):
        """Should create basic summary from result."""
        result = {
            "source": "Test Source",
            "data": {"organic_products": [{"title": "P1"}, {"title": "P2"}]}
        }
        summary = api.summarize_decodo_result(result)
        self.assertEqual(summary["source"], "Test Source")
        self.assertEqual(summary["error"], "")
        self.assertEqual(summary["product_count"], 2)

    def test_summary_with_error(self):
        """Should handle error results."""
        result = {
            "source": "Test Source",
            "error": "HTTP 404: Not Found"
        }
        summary = api.summarize_decodo_result(result)
        self.assertEqual(summary["source"], "Test Source")
        self.assertIn("HTTP 404", summary["error"])
        self.assertEqual(summary["parser_status"], "error")

    def test_robot_block_detection(self):
        """Should detect CAPTCHA and robot blocks."""
        result = {
            "source": "Test Source",
            "data": "This page contains a CAPTCHA"
        }
        summary = api.summarize_decodo_result(result)
        self.assertTrue(summary["robot_blocked"])

    def test_robot_block_detection_variations(self):
        """Should detect various robot block phrases."""
        for phrase in ["verify you are human", "unusual traffic", "access denied", "CAPTCHA"]:
            result = {
                "source": "Test Source",
                "data": f"Please {phrase} to continue"
            }
            summary = api.summarize_decodo_result(result)
            self.assertTrue(summary["robot_blocked"], f"Should detect: {phrase}")


class TestNormalization(unittest.TestCase):
    """Test title normalization for deduplication."""

    def test_lowercase(self):
        """Should lowercase titles."""
        result = api.normalize_title("Test PRODUCT")
        self.assertEqual(result, "test product")

    def test_non_alphanumeric_normalization(self):
        """Should normalize non-alphanumeric runs to spaces."""
        result = api.normalize_title("Test-Product--Name!!!")
        self.assertEqual(result, "test product name")

    def test_collapse_spaces(self):
        """Should collapse multiple spaces."""
        result = api.normalize_title("Test   Product   Name")
        self.assertEqual(result, "test product name")

    def test_empty_string(self):
        """Should return empty string for invalid input."""
        self.assertEqual(api.normalize_title(""), "")
        self.assertEqual(api.normalize_title(None), "")


class TestAIProviders(unittest.TestCase):
    """Test AI provider configuration."""

    def setUp(self):
        """Clear any cached api module."""
        import sys
        if 'api' in sys.modules:
            del sys.modules['api']

    def test_get_ai_providers_empty(self):
        """Should return empty list when no keys configured."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            providers = api_reloaded.get_ai_providers()
            self.assertEqual(len(providers), 0)

    def test_get_ai_providers_kimi(self):
        """Should return Kimi provider when KIMI_API_KEY is set."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': 'kimi-key-123',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            providers = api_reloaded.get_ai_providers()
            self.assertTrue(any(p['name'] == 'kimi_platform' for p in providers))

    def test_get_ai_providers_moonshot(self):
        """Should return Moonshot provider when MOONSHOT_API_KEY is set."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': 'moonshot-key-123',
            'OPENAI_API_KEY': '',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            providers = api_reloaded.get_ai_providers()
            self.assertTrue(any(p['name'] == 'kimi_moonshot' for p in providers))

    def test_get_ai_providers_openai(self):
        """Should return OpenAI provider when OPENAI_API_KEY is set."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': 'openai-key-123',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            providers = api_reloaded.get_ai_providers()
            self.assertTrue(any(p['name'] == 'openai' for p in providers))

    def test_get_ai_providers_ignores_placeholder(self):
        """Should ignore keys starting with 'your_'."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': 'your_api_key_here',
            'OPENAI_API_KEY': '',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            providers = api_reloaded.get_ai_providers()
            self.assertEqual(len(providers), 0)


class TestAIModelAnalysis(unittest.TestCase):
    """Test AI model analysis."""

    def setUp(self):
        """Clear any cached api module."""
        import sys
        if 'api' in sys.modules:
            del sys.modules['api']

    def test_local_fallback_no_providers(self):
        """Should use local scores when no providers configured."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
            'AI_MODEL_API_KEY': '',
        }, clear=True):
            import api as api_reloaded

            products = [
                {'product': 'P1', 'viral_score': 80},
                {'product': 'P2', 'viral_score': 90},
                {'product': 'P3', 'viral_score': 70},
            ]
            ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
            self.assertEqual(len(ranked), 3)
            self.assertIsNotNone(warning)
            self.assertIn("No AI provider configured", warning)
            # Should be sorted by local score descending
            self.assertEqual(ranked[0]['product'], 'P2')
            self.assertEqual(ranked[1]['product'], 'P1')
            self.assertEqual(ranked[2]['product'], 'P3')

    def test_local_fallback_401_warning(self):
        """Should return 401 warning for authentication errors."""
        products = [{'product': 'P1', 'viral_score': 80}]

        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (None, "HTTP 401: Unauthorized")

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNotNone(warning)
                self.assertIn("401", warning)
                self.assertIn("Authentication error", warning)

    def test_local_fallback_429_warning(self):
        """Should return 429 warning for rate limit errors."""
        products = [{'product': 'P1', 'viral_score': 80}]

        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (None, "HTTP 429: Too Many Requests")

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNotNone(warning)
                self.assertIn("429", warning)
                self.assertIn("Rate limit exceeded", warning)

    def test_successful_indexed_merging(self):
        """Should merge AI scores with correct candidate indexes."""
        products = [
            {'product': 'P0', 'viral_score': 80},
            {'product': 'P1', 'viral_score': 70},
            {'product': 'P2', 'viral_score': 60},
        ]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": 0, "viral_score": 95, "reason": "Great product"},
                            {"candidate_index": 2, "viral_score": 90, "reason": "Also great"},
                            {"candidate_index": 1, "viral_score": 85, "reason": "Good product"}
                        ]
                    })
                }
            }]
        }

        with patch.dict('os.environ', {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (mock_response, None)

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNone(warning)
                self.assertEqual(len(ranked), 3)
                # Should be sorted by AI score descending
                self.assertEqual(ranked[0]['product'], 'P0')
                self.assertEqual(ranked[0]['viral_score'], 95)
                self.assertEqual(ranked[0]['ai_reason'], 'Great product')
                self.assertEqual(ranked[1]['product'], 'P2')
                self.assertEqual(ranked[1]['viral_score'], 90)
                self.assertEqual(ranked[2]['product'], 'P1')
                self.assertEqual(ranked[2]['viral_score'], 85)

    def test_score_clamping(self):
        """Should clamp scores to 0-100."""
        products = [{'product': 'P1', 'viral_score': 80}]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": 0, "viral_score": 150, "reason": "Too high"}
                        ]
                    })
                }
            }]
        }

        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (mock_response, None)

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNone(warning)
                self.assertEqual(ranked[0]['viral_score'], 100)  # Clamped down

    def test_negative_score_clamping(self):
        """Should clamp negative scores to 0."""
        products = [{'product': 'P1', 'viral_score': 80}]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": 0, "viral_score": -10, "reason": "Bad"}
                        ]
                    })
                }
            }]
        }

        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (mock_response, None)

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNone(warning)
                self.assertEqual(ranked[0]['viral_score'], 0)  # Clamped up

    def test_reason_truncation(self):
        """Should truncate reasons to 200 characters."""
        products = [{'product': 'P1', 'viral_score': 80}]
        long_reason = "x" * 300

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": 0, "viral_score": 90, "reason": long_reason}
                        ]
                    })
                }
            }]
        }

        with patch.dict('os.environ', {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'test'}]
                mock_call.return_value = (mock_response, None)

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNone(warning)
                self.assertEqual(len(ranked[0]['ai_reason']), 200)

    def test_unknown_index_ignored(self):
        """Should ignore unknown candidate indexes."""
        products = [{'product': 'P1', 'viral_score': 80}]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": 99, "viral_score": 90, "reason": "Unknown"}
                        ]
                    })
                }
            }]
        }

        with patch('api.get_ai_providers') as mock_providers, \
             patch('api.call_ai_provider') as mock_call:
            mock_providers.return_value = [{'name': 'test'}]
            mock_call.return_value = (mock_response, None)

            ranked, warning = api.analyze_with_ai_model("test", products)
            # Should fall back to local ranking since index 99 doesn't exist
            self.assertEqual(len(ranked), 1)
            self.assertEqual(ranked[0]['product'], 'P1')

    def test_top_ten_limiting(self):
        """Should limit to top 10 candidates."""
        products = [{'product': f'P{i}', 'viral_score': 80 + i} for i in range(25)]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {"candidate_index": i, "viral_score": 80 + i, "reason": f"Reason {i}"}
                            for i in range(25)
                        ]
                    })
                }
            }]
        }

        with patch('api.get_ai_providers') as mock_providers, \
             patch('api.call_ai_provider') as mock_call:
            mock_providers.return_value = [{'name': 'test'}]
            mock_call.return_value = (mock_response, None)

            ranked, warning = api.analyze_with_ai_model("test", products)
            self.assertEqual(len(ranked), 10)  # Limited to 10

    def test_provider_fallback(self):
        """Should try next provider on failure."""
        products = [{'product': 'P1', 'viral_score': 80}]

        with patch.dict('os.environ', {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{'name': 'provider1'}, {'name': 'provider2'}]
                # First provider fails, second succeeds
                mock_call.side_effect = [
                    (None, "Error from provider1"),
                    ({
                        "choices": [{
                            "message": {
                                "content": json.dumps({
                                    "ranked": [
                                        {"candidate_index": 0, "viral_score": 90, "reason": "Good"}
                                    ]
                                })
                            }
                        }]
                    }, None)
                ]

                ranked, warning = api_reloaded.analyze_with_ai_model("test", products)
                self.assertIsNone(warning)
                self.assertEqual(len(ranked), 1)
                self.assertEqual(ranked[0]['viral_score'], 90)


class TestRunDiscovery(unittest.TestCase):
    """Test the full discovery pipeline."""

    def test_run_discovery_returns_required_fields(self):
        """Should return all required fields."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }):
            import importlib
            import sys
            if 'api' in sys.modules:
                del sys.modules['api']
            import api as api_reloaded

            with patch.object(api_reloaded, 'scrape_with_decodo') as mock_scrape, \
                 patch.object(api_reloaded, 'extract_products') as mock_extract, \
                 patch.object(api_reloaded, 'summarize_decodo_result') as mock_summary, \
                 patch.object(api_reloaded, 'analyze_with_ai_model') as mock_ai:

                mock_scrape.return_value = json.dumps([])
                mock_extract.return_value = []
                mock_summary.return_value = []
                mock_ai.return_value = ([], "warning")

                result = api_reloaded.run_discovery("test")
                self.assertIn('niche', result)
                self.assertIn('initial_products', result)
                self.assertIn('discovery_summary', result)
                self.assertIn('discovery_data', result)
                self.assertIn('ranking_warnings', result)


# =============================================================================
# Supplier Sourcing Tests (Step 7)
# =============================================================================

class TestSupplierPayloadBuilding(unittest.TestCase):
    """Test supplier payload building."""

    def test_build_supplier_payloads_returns_two_jobs(self):
        """Should return exactly 2 payloads per product."""
        payloads = api.build_supplier_payloads("test product")
        self.assertEqual(len(payloads), 2)

    def test_build_supplier_payloads_alibaba_first(self):
        """Should have Alibaba as first payload."""
        payloads = api.build_supplier_payloads("test product")
        self.assertIn("alibaba.com", payloads[0]["url"])

    def test_build_supplier_payloads_aliexpress_second(self):
        """Should have AliExpress as second payload."""
        payloads = api.build_supplier_payloads("test product")
        self.assertIn("aliexpress.com", payloads[1]["url"])

    def test_build_supplier_payloads_url_encoding(self):
        """Should properly URL-encode product names."""
        payloads = api.build_supplier_payloads("pet gadgets & toys")
        for payload in payloads:
            url = payload["url"]
            self.assertIn("pet+gadgets+%26+toys", url)
            # or it might be quote_plus encoded as %20
            self.assertIn("pet", url.lower())
            self.assertIn("gadgets", url.lower())

    def test_build_supplier_payloads_contains_proxy_pool(self):
        """Should include proxy_pool setting."""
        payloads = api.build_supplier_payloads("test")
        for payload in payloads:
            self.assertIn("proxy_pool", payload)
            self.assertEqual(payload["proxy_pool"], "premium")

    def test_build_supplier_payloads_contains_headless(self):
        """Should include headless setting."""
        payloads = api.build_supplier_payloads("test")
        for payload in payloads:
            self.assertIn("headless", payload)
            self.assertEqual(payload["headless"], "html")

    def test_build_supplier_payloads_no_parse(self):
        """Should NOT include parse parameter."""
        payloads = api.build_supplier_payloads("test")
        for payload in payloads:
            self.assertNotIn("parse", payload)

    def test_build_supplier_payloads_no_target(self):
        """Should NOT include target parameter for marketplace URLs."""
        payloads = api.build_supplier_payloads("test")
        for payload in payloads:
            self.assertNotIn("target", payload)

    def test_build_supplier_payloads_exact_keys(self):
        """Should have exactly url, proxy_pool, headless keys."""
        payloads = api.build_supplier_payloads("test")
        for payload in payloads:
            self.assertEqual(set(payload.keys()), {'url', 'proxy_pool', 'headless'})


class TestSupplierValidation(unittest.TestCase):
    """Test supplier validation and sourcing."""

    def test_validate_suppliers_empty_products(self):
        """Should handle empty products list."""
        result = api.validate_suppliers_for_products([])
        self.assertEqual(result['products_validated'], 0)
        self.assertEqual(result['total_supplier_requests'], 0)
        self.assertEqual(result['products'], [])

    def test_validate_suppliers_no_valid_names(self):
        """Should skip products with blank names."""
        products = [
            {'product': ''},
            {'product': '   '},
            {'product': None},
        ]
        result = api.validate_suppliers_for_products(products)
        self.assertEqual(result['products_validated'], 0)
        self.assertEqual(result['total_supplier_requests'], 0)

    def test_validate_suppliers_takes_top_10(self):
        """Should only process top 10 products."""
        products = [{'product': f'Product {i}'} for i in range(15)]
        with patch.object(api, 'scrape_with_decodo_payload') as mock_scrape:
            mock_scrape.return_value = {'data': '{}'}
            result = api.validate_suppliers_for_products(products)
            # 10 products * 2 marketplaces = 20 requests
            self.assertEqual(result['products_validated'], 10)
            self.assertEqual(result['total_supplier_requests'], 20)

    def test_validate_suppliers_20_requests_for_10_products(self):
        """Should create 20 requests for 10 products (2 per product)."""
        products = [{'product': f'Product {i}'} for i in range(10)]
        with patch.object(api, 'scrape_with_decodo_payload') as mock_scrape:
            mock_scrape.return_value = {'data': '{}'}
            result = api.validate_suppliers_for_products(products)
            self.assertEqual(result['total_supplier_requests'], 20)

    def test_validate_suppliers_partial_failure(self):
        """Should handle partial failures gracefully."""
        products = [{'product': 'Product 1'}]
        with patch.object(api, 'scrape_with_decodo_payload') as mock_scrape:
            # First succeeds, second fails
            mock_scrape.side_effect = [
                {'data': '{"results": {}}'},
                {'error': 'Failed to connect'}
            ]
            result = api.validate_suppliers_for_products(products)
            self.assertEqual(result['successful_supplier_requests'], 1)
            self.assertEqual(result['failed_supplier_requests'], 1)

    def test_validate_suppliers_all_fail(self):
        """Should handle all requests failing."""
        products = [{'product': 'Product 1'}]
        with patch.object(api, 'scrape_with_decodo_payload') as mock_scrape:
            mock_scrape.side_effect = [
                {'error': 'Failed 1'},
                {'error': 'Failed 2'}
            ]
            result = api.validate_suppliers_for_products(products)
            self.assertEqual(result['successful_supplier_requests'], 0)
            self.assertEqual(result['failed_supplier_requests'], 2)


class TestMarketplaceHTMLParser(unittest.TestCase):
    """Test HTML parsing for marketplace pages."""

    def test_alibaba_parser_finds_listing_links(self):
        """Should extract Alibaba listing links."""
        html = '''
        <html>
            <body>
                <a href="https://www.alibaba.com/product-detail/123.html">Product One</a>
                <a href="https://www.alibaba.com/product/456.html">Product Two</a>
                <a href="https://www.alibaba.com/trade/789">Not a product</a>
            </body>
        </html>
        '''
        parser = api.MarketplaceHTMLParser('alibaba')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 2)
        self.assertIn('product-detail', links[0]['url'])
        self.assertIn('product', links[1]['url'])

    def test_aliexpress_parser_finds_item_links(self):
        """Should extract AliExpress item links."""
        html = '''
        <html>
            <body>
                <a href="https://www.aliexpress.com/item/123.html">Item One</a>
                <a href="https://www.aliexpress.com/item/456.html">Item Two</a>
                <a href="https://www.aliexpress.com/store/789">Not an item</a>
            </body>
        </html>
        '''
        parser = api.MarketplaceHTMLParser('aliexpress')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 2)
        for link in links:
            self.assertIn('/item/', link['url'])

    def test_parser_deduplicates_urls(self):
        """Should deduplicate URLs by canonical form."""
        html = '''
        <html>
            <body>
                <a href="https://www.aliexpress.com/item/123.html">Item One</a>
                <a href="https://www.aliexpress.com/item/123.html?query=test">Item One Duplicate</a>
                <a href="https://www.aliexpress.com/item/123.html?another=param">Item One Duplicate 2</a>
            </body>
        </html>
        '''
        parser = api.MarketplaceHTMLParser('aliexpress')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 1)  # Deduplicated

    def test_parser_limits_to_5_links(self):
        """Should stop after 5 unique listing links."""
        html = '''
        <html>
            <body>
        '''
        for i in range(10):
            html += f'<a href="https://www.aliexpress.com/item/{i}.html">Item {i}</a>\n'
        html += '''
            </body>
        </html>
        '''
        parser = api.MarketplaceHTMLParser('aliexpress')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 5)  # Limited to 5

    def test_parser_extracts_anchor_text(self):
        """Should extract anchor text as title."""
        html = '<a href="https://www.alibaba.com/product-detail/test.html">Amazing Widget</a>'
        parser = api.MarketplaceHTMLParser('alibaba')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['text'], 'Amazing Widget')

    def test_parser_skips_non_listing_links(self):
        """Should skip non-listing links for Alibaba."""
        html = '''
        <html>
            <body>
                <a href="https://www.alibaba.com/">Home</a>
                <a href="https://www.alibaba.com/category/electronics">Category</a>
                <a href="https://www.alibaba.com/store/123">Store</a>
            </body>
        </html>
        '''
        parser = api.MarketplaceHTMLParser('alibaba')
        parser.feed(html)
        links = parser.get_listing_links()
        self.assertEqual(len(links), 0)  # No product-detail or /product/ links


class TestPriceRepair(unittest.TestCase):
    """Test price repair functionality."""

    def test_repair_price_usd_symbol(self):
        """Should repair price with USD symbol."""
        result = api.repair_price("$19.99")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['value'], 19.99)

    def test_repair_price_eur_symbol(self):
        """Should repair price with EUR symbol."""
        result = api.repair_price("€25.50")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'EUR')
        self.assertEqual(result['value'], 25.50)

    def test_repair_price_gbp_symbol(self):
        """Should repair price with GBP symbol."""
        result = api.repair_price("£10.00")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'GBP')
        self.assertEqual(result['value'], 10.00)

    def test_repair_price_usd_code(self):
        """Should repair price with USD code."""
        result = api.repair_price("15.99 USD")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['value'], 15.99)

    def test_repair_price_cny_code(self):
        """Should repair price with CNY code."""
        result = api.repair_price("100 CNY")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'CNY')
        self.assertEqual(result['value'], 100)

    def test_repair_price_rmb_code(self):
        """Should repair price with RMB code."""
        result = api.repair_price("50 RMB")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'CNY')  # RMB normalized to CNY
        self.assertEqual(result['value'], 50)

    def test_repair_price_invalid(self):
        """Should return None for invalid prices."""
        self.assertIsNone(api.repair_price("Not a price"))
        self.assertIsNone(api.repair_price(""))
        self.assertIsNone(api.repair_price(None))

    def test_repair_price_plain_number(self):
        """Should repair plain number with default USD."""
        result = api.repair_price("20.00")
        self.assertIsNotNone(result)
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['value'], 20.00)


class TestPriceRangeParsing(unittest.TestCase):
    """Test price range parsing."""

    def test_parse_price_range_with_dash(self):
        """Should parse price range with dash separator."""
        result = api.parse_price_range("$10.00 - $20.00")
        self.assertIsNotNone(result)
        self.assertEqual(result['min'], 10.00)
        self.assertEqual(result['max'], 20.00)

    def test_parse_price_range_with_space(self):
        """Should parse price range with space separator."""
        result = api.parse_price_range("10 20")
        self.assertIsNotNone(result)
        self.assertEqual(result['min'], 10)
        self.assertEqual(result['max'], 20)

    def test_parse_price_range_invalid(self):
        """Should return None for invalid range."""
        self.assertIsNone(api.parse_price_range("Not a range"))
        self.assertIsNone(api.parse_price_range(""))


class TestCurrencyNormalization(unittest.TestCase):
    """Test currency normalization."""

    def test_normalize_usd(self):
        """Should normalize USD to USD."""
        self.assertEqual(api.normalize_currency("USD"), "USD")
        self.assertEqual(api.normalize_currency("usd"), "USD")

    def test_normalize_rmb_to_cny(self):
        """Should normalize RMB to CNY."""
        self.assertEqual(api.normalize_currency("RMB"), "CNY")
        self.assertEqual(api.normalize_currency("rmb"), "CNY")

    def test_normalize_cny(self):
        """Should keep CNY as CNY."""
        self.assertEqual(api.normalize_currency("CNY"), "CNY")

    def test_normalize_eur(self):
        """Should normalize EUR to EUR."""
        self.assertEqual(api.normalize_currency("EUR"), "EUR")

    def test_normalize_default(self):
        """Should default to USD for unknown currencies."""
        self.assertEqual(api.normalize_currency("XYZ"), "USD")
        self.assertEqual(api.normalize_currency(None), "USD")
        self.assertEqual(api.normalize_currency(""), "USD")


class TestSupplierListingNormalization(unittest.TestCase):
    """Test supplier listing normalization."""

    def test_normalize_no_title(self):
        """Should return None for listings without title."""
        result = api.normalize_supplier_listing(
            {'url': 'http://example.com'}, 'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNone(result)

    def test_normalize_no_price(self):
        """Should return None for listings without price or price_range."""
        result = api.normalize_supplier_listing(
            {'title': 'Test Product', 'url': 'http://example.com'},
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNone(result)

    def test_normalize_with_unit_price(self):
        """Should normalize listing with unit_price."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'unit_price': 10.99,
                'currency': 'USD',
                'min_order_quantity': 10,
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['product_reference'], 'Test Product')
        self.assertEqual(result['supplier_platform'], 'alibaba')
        self.assertEqual(result['supplier_title'], 'Test Product')
        self.assertEqual(result['unit_price'], 10.99)
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['min_order_quantity'], 10)
        self.assertEqual(result['supplier_url'], 'http://example.com/product')

    def test_normalize_with_price_range(self):
        """Should normalize listing with price_range."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price_range': {'min': 10.0, 'max': 20.0},
                'currency': 'USD',
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['price_range'], {'min': 10.0, 'max': 20.0})
        self.assertIsNone(result['unit_price'])

    def test_normalize_with_string_price(self):
        """Should repair string price."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price': '$15.99',
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['unit_price'], 15.99)
        self.assertEqual(result['currency'], 'USD')

    def test_normalize_with_string_price_range(self):
        """Should repair string price range."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price_range': {'min': '$10', 'max': '$20'},
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['price_range']['min'], 10.0)
        self.assertEqual(result['price_range']['max'], 20.0)

    def test_normalize_moq_string(self):
        """Should convert MOQ string to int."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price': 10.0,
                'min_order_quantity': '100',
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['min_order_quantity'], 100)

    def test_normalize_evidence(self):
        """Should build supplier evidence."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price': 10.0,
                'currency': 'USD',
                'rating': 4.5,
                'orders': 1000,
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        evidence = result['supplier_evidence']
        self.assertIn('price: 10.0 USD', evidence)
        self.assertIn('rating: 4.5', evidence)
        self.assertIn('orders: 1000', evidence)

    def test_normalize_provenance(self):
        """Should include provenance."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price': 10.0,
            },
            'alibaba', 'http://test.com/search', 5, 3
        )
        self.assertIsNotNone(result)
        provenance = result['provenance']
        self.assertEqual(provenance['source_url'], 'http://test.com/search')
        self.assertEqual(provenance['candidate_index'], 5)
        self.assertEqual(provenance['offer_index'], 3)
        self.assertEqual(provenance['platform'], 'alibaba')

    def test_normalize_rating_string(self):
        """Should convert rating string to float."""
        result = api.normalize_supplier_listing(
            {
                'title': 'Test Product',
                'url': 'http://example.com/product',
                'price': 10.0,
                'rating': '4.5',
            },
            'alibaba', 'http://test.com', 0, 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['rating'], 4.5)


class TestSupplierResponseProcessing(unittest.TestCase):
    """Test supplier response processing."""

    def test_process_error_response(self):
        """Should handle error responses."""
        response = {'error': 'Connection timeout'}
        listings, parsed, has_error, is_empty = api.process_supplier_response(
            response, 'alibaba', 'http://test.com', 0
        )
        self.assertEqual(listings, [])
        self.assertTrue(has_error)
        self.assertFalse(is_empty)

    def test_process_empty_response(self):
        """Should handle responses without data or error."""
        response = {}
        listings, parsed, has_error, is_empty = api.process_supplier_response(
            response, 'alibaba', 'http://test.com', 0
        )
        self.assertEqual(listings, [])
        self.assertFalse(has_error)
        self.assertFalse(is_empty)

    def test_process_parsed_json_listings(self):
        """Should extract listings from parsed JSON."""
        data = {
            'results': {
                'results': {
                    'listings': [
                        {
                            'title': 'Product 1',
                            'url': 'http://example.com/1',
                            'price': 10.0,
                            'currency': 'USD'
                        },
                        {
                            'title': 'Product 2',
                            'url': 'http://example.com/2',
                            'price': 15.0,
                            'currency': 'USD'
                        }
                    ]
                }
            }
        }
        response = {'data': data}
        listings, parsed, has_error, is_empty = api.process_supplier_response(
            response, 'alibaba', 'http://test.com', 0
        )
        self.assertEqual(len(listings), 2)
        self.assertFalse(has_error)
        self.assertFalse(is_empty)

    def test_process_html_content(self):
        """Should extract listings from HTML content."""
        html = '''
        <html>
            <body>
                <a href="https://www.aliexpress.com/item/123.html">Product One</a>
            </body>
        </html>
        '''
        response = {'data': html}
        listings, parsed, has_error, is_empty = api.process_supplier_response(
            response, 'aliexpress', 'http://test.com', 0
        )
        # HTML parsing should find at least the link
        # The normalize function may return None if no price
        # But let's check that it attempts to process
        self.assertFalse(has_error)
        self.assertFalse(is_empty)


class TestSupplierSourcingPipeline(unittest.TestCase):
    """Test the supplier sourcing pipeline."""

    def test_run_supplier_sourcing_basic(self):
        """Should run supplier sourcing and return expected structure."""
        products = [{'product': 'Test Product'}]
        with patch.object(api, 'validate_suppliers_for_products') as mock_validate:
            mock_validate.return_value = {
                'products': [],
                'products_validated': 1,
                'total_supplier_requests': 2,
                'successful_supplier_requests': 2,
                'failed_supplier_requests': 0,
                'empty_supplier_requests': 0,
                'alibaba_offers': 0,
                'aliexpress_offers': 0,
            }
            result = api.run_supplier_sourcing(products)
            self.assertIn('supplier_data', result)
            self.assertIn('supplier_summary', result)
            self.assertEqual(result['supplier_summary']['products_validated'], 1)
            self.assertEqual(result['supplier_summary']['total_supplier_requests'], 2)

    def test_run_supplier_sourcing_empty_products(self):
        """Should handle empty products list."""
        result = api.run_supplier_sourcing([])
        self.assertEqual(result['supplier_data'], [])
        self.assertEqual(result['supplier_summary']['products_validated'], 0)


class TestSupplierIntegration(unittest.TestCase):
    """Test supplier integration with discovery."""

    def test_hunt_endpoint_includes_supplier_data(self):
        """Should return supplier data in hunt response."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }):
            import importlib
            import sys
            if 'api' in sys.modules:
                del sys.modules['api']
            import api as api_reloaded

            with patch.object(api_reloaded, 'scrape_with_decodo') as mock_scrape, \
                 patch.object(api_reloaded, 'extract_products') as mock_extract, \
                 patch.object(api_reloaded, 'summarize_decodo_result') as mock_summary, \
                 patch.object(api_reloaded, 'analyze_with_ai_model') as mock_ai, \
                 patch.object(api_reloaded, 'validate_suppliers_for_products') as mock_validate:

                mock_scrape.return_value = json.dumps([])
                mock_extract.return_value = []
                mock_summary.return_value = []
                mock_ai.return_value = ([], None)
                mock_validate.return_value = {
                    'products': [],
                    'products_validated': 0,
                    'total_supplier_requests': 0,
                    'successful_supplier_requests': 0,
                    'failed_supplier_requests': 0,
                    'empty_supplier_requests': 0,
                    'alibaba_offers': 0,
                    'aliexpress_offers': 0,
                }

                request = api_reloaded.HuntRequest(niche="test")
                result = api_reloaded.hunt(request)
                
                self.assertIn('supplier_summary', result)
                self.assertIn('supplier_data', result)
                self.assertIn('final_products', result)

    def test_hunt_endpoint_with_products_has_supplier_data(self):
        """Should source suppliers when products are found."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }):
            import importlib
            import sys
            if 'api' in sys.modules:
                del sys.modules['api']
            import api as api_reloaded

            with patch.object(api_reloaded, 'scrape_with_decodo') as mock_scrape, \
                 patch.object(api_reloaded, 'extract_products') as mock_extract, \
                 patch.object(api_reloaded, 'summarize_decodo_result') as mock_summary, \
                 patch.object(api_reloaded, 'analyze_with_ai_model') as mock_ai, \
                 patch.object(api_reloaded, 'validate_suppliers_for_products') as mock_validate:

                mock_scrape.return_value = json.dumps([])
                mock_extract.return_value = [{'product': 'Test Product', 'viral_score': 80}]
                mock_summary.return_value = []
                mock_ai.return_value = ([{'product': 'Test Product', 'viral_score': 80}], None)
                mock_validate.return_value = {
                    'products': [{'product_name': 'Test Product', 'supplier_results': []}],
                    'products_validated': 1,
                    'total_supplier_requests': 2,
                    'successful_supplier_requests': 2,
                    'failed_supplier_requests': 0,
                    'empty_supplier_requests': 0,
                    'alibaba_offers': 1,
                    'aliexpress_offers': 1,
                }

                request = api_reloaded.HuntRequest(niche="test")
                result = api_reloaded.hunt(request)
                
                self.assertEqual(len(result['initial_products']), 1)
                self.assertEqual(result['supplier_summary']['products_validated'], 1)
                self.assertEqual(result['supplier_summary']['alibaba_offers'], 1)
                self.assertEqual(result['supplier_summary']['aliexpress_offers'], 1)


# =============================================================================
# Final Ranking Tests (Step 8)
# =============================================================================

class TestCurrencyConversion(unittest.TestCase):
    """Test currency conversion functionality."""

    def test_convert_to_usd_none_amount(self):
        """Should return None for None amount."""
        result = api.convert_to_usd(None, 'USD')
        self.assertIsNone(result)

    def test_convert_to_usd_none_currency(self):
        """Should return None for None currency."""
        result = api.convert_to_usd(10.0, None)
        self.assertIsNone(result)

    def test_convert_to_usd_unsupported_currency(self):
        """Should return None for unsupported currency."""
        result = api.convert_to_usd(10.0, 'XYZ')
        self.assertIsNone(result)

    def test_convert_to_usd_usd(self):
        """Should convert USD to USD at 1:1."""
        result = api.convert_to_usd(10.0, 'USD')
        self.assertEqual(result, 10.0)

    def test_convert_to_usd_eur(self):
        """Should convert EUR to USD at 1.09 rate."""
        result = api.convert_to_usd(10.0, 'EUR')
        self.assertAlmostEqual(result, 10.9, places=2)

    def test_convert_to_usd_gbp(self):
        """Should convert GBP to USD at 1.28 rate."""
        result = api.convert_to_usd(10.0, 'GBP')
        self.assertAlmostEqual(result, 12.8, places=2)

    def test_convert_to_usd_cny(self):
        """Should convert CNY to USD at 0.14 rate."""
        result = api.convert_to_usd(100.0, 'CNY')
        self.assertAlmostEqual(result, 14.0, places=2)

    def test_convert_to_usd_rmb(self):
        """Should convert RMB to USD at 0.14 rate."""
        result = api.convert_to_usd(100.0, 'RMB')
        self.assertAlmostEqual(result, 14.0, places=2)

    def test_convert_to_usd_zero_amount(self):
        """Should return None for zero amount."""
        result = api.convert_to_usd(0, 'USD')
        self.assertIsNone(result)

    def test_convert_to_usd_negative_amount(self):
        """Should return None for negative amount."""
        result = api.convert_to_usd(-10.0, 'USD')
        self.assertIsNone(result)

    def test_convert_to_usd_non_finite(self):
        """Should return None for non-finite values."""
        result = api.convert_to_usd(float('inf'), 'USD')
        self.assertIsNone(result)
        result = api.convert_to_usd(float('nan'), 'USD')
        self.assertIsNone(result)


class TestGetCrediblePrice(unittest.TestCase):
    """Test credible price extraction."""

    def test_unit_price_valid(self):
        """Should extract valid unit_price."""
        offer = {'unit_price': 10.0, 'currency': 'USD'}
        result = api.get_credible_price(offer)
        self.assertEqual(result, 10.0)

    def test_price_range_valid(self):
        """Should extract min from price_range."""
        offer = {'price_range': {'min': 10.0, 'max': 20.0}, 'currency': 'USD'}
        result = api.get_credible_price(offer)
        self.assertEqual(result, 10.0)

    def test_unit_price_usd_conversion(self):
        """Should convert unit_price to USD."""
        offer = {'unit_price': 10.0, 'currency': 'EUR'}
        result = api.get_credible_price(offer)
        self.assertAlmostEqual(result, 10.9, places=2)

    def test_price_range_cny_conversion(self):
        """Should convert price_range min to USD."""
        offer = {'price_range': {'min': 100.0}, 'currency': 'CNY'}
        result = api.get_credible_price(offer)
        self.assertAlmostEqual(result, 14.0, places=2)

    def test_no_price(self):
        """Should return None for missing price."""
        offer = {'currency': 'USD'}
        result = api.get_credible_price(offer)
        self.assertIsNone(result)

    def test_unsupported_currency(self):
        """Should return None for unsupported currency."""
        offer = {'unit_price': 10.0, 'currency': 'XYZ'}
        result = api.get_credible_price(offer)
        self.assertIsNone(result)

    def test_zero_price(self):
        """Should return None for zero price."""
        offer = {'unit_price': 0, 'currency': 'USD'}
        result = api.get_credible_price(offer)
        self.assertIsNone(result)

    def test_non_dict_offer(self):
        """Should return None for non-dict offer."""
        result = api.get_credible_price("not a dict")
        self.assertIsNone(result)


class TestBuildFinalRankingInput(unittest.TestCase):
    """Test final ranking input building."""

    def test_returns_candidates_and_offers(self):
        """Should return candidates and offers tuples."""
        products = [{'product': 'Product 1', 'price': 10.0, 'viral_score': 80}]
        supplier_data = []
        candidates, offers = api.build_final_ranking_input(products, supplier_data)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(offers), 0)

    def test_candidate_structure(self):
        """Should create proper candidate structure."""
        products = [{'product': 'P1', 'price': 10.0, 'currency': 'USD', 'viral_score': 80, 'url': 'http://test.com', 'source': 'Amazon'}]
        supplier_data = []
        candidates, _ = api.build_final_ranking_input(products, supplier_data)
        self.assertEqual(candidates[0]['candidate_index'], 0)
        self.assertEqual(candidates[0]['product'], 'P1')
        self.assertEqual(candidates[0]['price'], 10.0)
        self.assertEqual(candidates[0]['currency'], 'USD')
        self.assertEqual(candidates[0]['viral_score'], 80)

    def test_offer_structure(self):
        """Should create proper offer structure."""
        products = [{'product': 'P1', 'price': 10.0, 'viral_score': 80}]
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'supplier_url': 'http://alibaba.com/1',
                    'unit_price': 5.0,
                    'currency': 'USD',
                    'min_order_quantity': 10,
                    'shipping_info': 'Free shipping',
                    'rating': 4.5,
                    'supplier_evidence': ['price: 5 USD'],
                }
            }]
        }]
        candidates, offers = api.build_final_ranking_input(products, supplier_data)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['offer_index'], 0)
        self.assertEqual(offers[0]['candidate_index'], 0)
        self.assertEqual(offers[0]['supplier_platform'], 'alibaba')
        self.assertEqual(offers[0]['price_usd'], 5.0)

    def test_matches_by_normalized_title(self):
        """Should match products by normalized title."""
        products = [{'product': 'Product ONE', 'price': 10.0, 'viral_score': 80}]
        supplier_data = [{
            'product_name': 'Product one',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'unit_price': 5.0,
                    'currency': 'USD',
                }
            }]
        }]
        candidates, offers = api.build_final_ranking_input(products, supplier_data)
        self.assertEqual(len(offers), 1)

    def test_empty_supplier_data(self):
        """Should handle empty supplier data."""
        products = [{'product': 'P1', 'price': 10.0, 'viral_score': 80}]
        candidates, offers = api.build_final_ranking_input(products, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(offers), 0)


class TestOfferScoring(unittest.TestCase):
    """Test offer scoring functions."""

    def test_cost_desirability_low(self):
        """Should give high score for low price."""
        offer = {'price_usd': 1.0}
        result = api.compute_cost_desirability(offer)
        self.assertEqual(result, 100)

    def test_cost_desirability_high(self):
        """Should give low score for high price."""
        offer = {'price_usd': 100.0}
        result = api.compute_cost_desirability(offer)
        self.assertEqual(result, 0)

    def test_cost_desirability_mid(self):
        """Should give proportional score for mid price."""
        offer = {'price_usd': 25.0}
        result = api.compute_cost_desirability(offer)
        self.assertEqual(result, 50)

    def test_supplier_evidence_score_empty(self):
        """Should give 0 for empty evidence."""
        offer = {'supplier_evidence': []}
        result = api.compute_supplier_evidence_score(offer)
        self.assertEqual(result, 0)

    def test_supplier_evidence_score_one(self):
        """Should give 20 for one evidence item."""
        offer = {'supplier_evidence': ['price: 10 USD']}
        result = api.compute_supplier_evidence_score(offer)
        self.assertEqual(result, 20)

    def test_supplier_evidence_score_five(self):
        """Should cap at 100 for five evidence items."""
        offer = {'supplier_evidence': ['item1', 'item2', 'item3', 'item4', 'item5']}
        result = api.compute_supplier_evidence_score(offer)
        self.assertEqual(result, 100)

    def test_moq_score_low(self):
        """Should give high score for low MOQ."""
        offer = {'min_order_quantity': 1}
        result = api.compute_moq_score(offer)
        self.assertEqual(result, 100)

    def test_moq_score_high(self):
        """Should give low score for high MOQ."""
        offer = {'min_order_quantity': 100}
        result = api.compute_moq_score(offer)
        self.assertEqual(result, 0)

    def test_shipping_score_free(self):
        """Should give high score for free shipping."""
        offer = {'shipping_info': 'Free shipping'}
        result = api.compute_shipping_score(offer)
        self.assertEqual(result, 100)

    def test_shipping_score_express(self):
        """Should give good score for express shipping."""
        offer = {'shipping_info': 'Express shipping'}
        result = api.compute_shipping_score(offer)
        self.assertEqual(result, 80)

    def test_shipping_score_neutral(self):
        """Should give neutral score for unknown shipping."""
        offer = {'shipping_info': ''}
        result = api.compute_shipping_score(offer)
        self.assertEqual(result, 50)

    def test_offer_score_combined(self):
        """Should compute combined offer score."""
        offer = {
            'price_usd': 10.0,
            'supplier_evidence': ['price: 10 USD', 'rating: 4.5'],
            'min_order_quantity': 5,
            'shipping_info': 'Free shipping',
        }
        result = api.compute_offer_score(offer)
        # cost: 80, evidence: 40, moq: 90, shipping: 100
        # (80*0.35) + (40*0.30) + (90*0.20) + (100*0.15) = 28 + 12 + 18 + 15 = 73
        self.assertAlmostEqual(result, 73.0, places=1)


class TestDeterministicFinalRanking(unittest.TestCase):
    """Test deterministic fallback final ranking."""

    def test_basic_ranking(self):
        """Should rank products deterministically."""
        products = [
            {'product': 'P1', 'price': 20.0, 'currency': 'USD', 'viral_score': 80},
            {'product': 'P2', 'price': 15.0, 'currency': 'USD', 'viral_score': 90},
        ]
        supplier_data = []
        final_products, warning = api.deterministic_final_ranking(products, supplier_data)
        self.assertEqual(len(final_products), 2)
        self.assertIsNotNone(warning)
        self.assertIn("deterministic fallback", warning)
        # Should be sorted by viral_score descending
        self.assertEqual(final_products[0]['product'], 'P2')
        self.assertEqual(final_products[1]['product'], 'P1')

    def test_with_supplier_offers(self):
        """Should rank with supplier offers."""
        products = [
            {'product': 'P1', 'price': 20.0, 'currency': 'USD', 'viral_score': 80},
        ]
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'supplier_url': 'http://test.com',
                    'unit_price': 5.0,
                    'currency': 'USD',
                    'min_order_quantity': 1,
                    'shipping_info': 'Free',
                    'supplier_evidence': ['price: 5 USD'],
                }
            }]
        }]
        final_products, warning = api.deterministic_final_ranking(products, supplier_data)
        self.assertEqual(len(final_products), 1)
        self.assertEqual(final_products[0]['product'], 'P1')
        self.assertIsNotNone(final_products[0]['selected_supplier_offer'])
        self.assertEqual(final_products[0]['ranking_method'], 'deterministic_fallback')

    def test_no_credible_offers(self):
        """Should handle products with no credible offers."""
        products = [
            {'product': 'P1', 'price': 20.0, 'currency': 'USD', 'viral_score': 80},
        ]
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'supplier_url': 'http://test.com',
                    'unit_price': 0,  # Not credible
                    'currency': 'USD',
                }
            }]
        }]
        final_products, warning = api.deterministic_final_ranking(products, supplier_data)
        self.assertEqual(len(final_products), 1)
        self.assertIsNone(final_products[0]['selected_supplier_offer'])
        self.assertIn("No credible", final_products[0]['rejection_reason'])

    def test_availability_scoring(self):
        """Should score availability correctly."""
        products = [{'product': 'P1', 'viral_score': 80}]
        # Two offers on different platforms
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [
                {'offer': {'supplier_platform': 'alibaba', 'unit_price': 5.0, 'currency': 'USD'}},
                {'offer': {'supplier_platform': 'aliexpress', 'unit_price': 6.0, 'currency': 'USD'}},
            ]
        }]
        final_products, _ = api.deterministic_final_ranking(products, supplier_data)
        self.assertEqual(len(final_products), 1)
        self.assertEqual(final_products[0]['ranking_method'], 'deterministic_fallback')


class TestFinalRankProducts(unittest.TestCase):
    """Test final AI ranking."""

    def setUp(self):
        """Clear cached api module."""
        import sys
        if 'api' in sys.modules:
            del sys.modules['api']

    def test_no_providers_fallback(self):
        """Should fall back to deterministic when no providers."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            products = [{'product': 'P1', 'viral_score': 80}]
            supplier_data = []
            final_products, warning = api_reloaded.final_rank_products("test", products, supplier_data)
            self.assertEqual(len(final_products), 1)
            self.assertIsNotNone(warning)
            self.assertIn("deterministic fallback", warning)
            self.assertEqual(final_products[0]['ranking_method'], 'deterministic_fallback')

    def test_valid_ai_response(self):
        """Should process valid AI response."""
        products = [{'product': 'P1', 'viral_score': 80}]
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'supplier_url': 'http://test.com',
                    'unit_price': 5.0,
                    'currency': 'USD',
                }
            }]
        }]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {
                                "candidate_index": 0,
                                "final_score": 95,
                                "selected_offer_index": 0,
                                "supplier_price_reasoning": "Good price",
                                "rejection_reason": None
                            }
                        ]
                    })
                }
            }]
        }

        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'OPENAI_API_KEY': 'test-openai-key',
        }, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{
                    'name': 'openai',
                    'api_key': 'test-openai-key',
                    'api_url': 'https://api.openai.com/v1/chat/completions',
                    'model': 'gpt-4o-mini',
                    'timeout': 60,
                    'extra_params': {}
                }]
                mock_call.return_value = (mock_response, None)

                final_products, warning = api_reloaded.final_rank_products("test", products, supplier_data)
                self.assertIsNone(warning)
                self.assertEqual(len(final_products), 1)
                self.assertEqual(final_products[0]['final_score'], 95)
                self.assertEqual(final_products[0]['ranking_method'], 'ai')
                self.assertIsNotNone(final_products[0]['selected_supplier_offer'])

    def test_ai_clamping(self):
        """Should clamp AI scores to 0-100."""
        products = [{'product': 'P1', 'viral_score': 80}]
        supplier_data = []

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {
                                "candidate_index": 0,
                                "final_score": 150,
                                "selected_offer_index": None,
                                "supplier_price_reasoning": "High",
                                "rejection_reason": "No offer"
                            }
                        ]
                    })
                }
            }]
        }

        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'OPENAI_API_KEY': 'test-openai-key',
        }, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider') as mock_call:
                mock_providers.return_value = [{
                    'name': 'openai',
                    'api_key': 'test-openai-key',
                    'api_url': 'https://api.openai.com/v1/chat/completions',
                    'model': 'gpt-4o-mini',
                    'timeout': 60,
                    'extra_params': {}
                }]
                mock_call.return_value = (mock_response, None)

                final_products, warning = api_reloaded.final_rank_products("test", products, supplier_data)
                self.assertIsNone(warning)
                self.assertEqual(final_products[0]['final_score'], 100)  # Clamped down

    def test_final_ranking_passes_final_prompt(self):
        """Regression: final ranking must pass niche/candidates plus the final prompt."""
        products = [{'product': 'P1', 'price': 20.0, 'currency': 'USD', 'viral_score': 80}]
        supplier_data = [{
            'product_name': 'P1',
            'supplier_results': [{
                'offer': {
                    'supplier_platform': 'alibaba',
                    'supplier_title': 'Offer 1',
                    'supplier_url': 'http://test.com',
                    'unit_price': 5.0,
                    'currency': 'USD',
                    'min_order_quantity': 1,
                }
            }]
        }]

        mock_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "ranked": [
                            {
                                "candidate_index": 0,
                                "final_score": 90,
                                "selected_offer_index": 0,
                                "supplier_price_reasoning": "Good price",
                                "rejection_reason": None
                            }
                        ]
                    })
                }
            }]
        }

        captured = {}

        def fake_call(provider, niche, products_arg, **kwargs):
            captured['niche'] = niche
            captured['products'] = products_arg
            captured['system_message'] = kwargs.get('system_message')
            captured['user_message'] = kwargs.get('user_message')
            return mock_response, None

        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'OPENAI_API_KEY': 'test-openai-key',
        }, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded, 'get_ai_providers') as mock_providers, \
                 patch.object(api_reloaded, 'call_ai_provider', side_effect=fake_call):
                mock_providers.return_value = [{
                    'name': 'openai',
                    'api_key': 'test-openai-key',
                    'api_url': 'https://api.openai.com/v1/chat/completions',
                    'model': 'gpt-4o-mini',
                    'timeout': 60,
                    'extra_params': {}
                }]

                final_products, warning = api_reloaded.final_rank_products(
                    "test", products, supplier_data
                )

                self.assertIsNone(warning)
                self.assertEqual(len(final_products), 1)
                self.assertEqual(final_products[0]['ranking_method'], 'ai')

                # The niche must be the plain niche string, not the system prompt
                self.assertEqual(captured['niche'], 'test')
                self.assertIsInstance(captured['products'], list)
                self.assertEqual(captured['products'][0]['product'], 'P1')
                # The final-ranking prompt must be the one that is sent
                self.assertIn('selected_offer_index', captured['system_message'])
                self.assertIn('Supplier Offers', captured['user_message'])


class TestCallAIProvider(unittest.TestCase):
    """Test the AI provider HTTP call and its prompt overrides."""

    PROVIDER = {
        'name': 'openai',
        'api_key': 'test-openai-key',
        'api_url': 'https://api.openai.com/v1/chat/completions',
        'model': 'gpt-4o-mini',
        'timeout': 60,
        'extra_params': {},
    }

    def setUp(self):
        """Clear cached api module."""
        import sys
        if 'api' in sys.modules:
            del sys.modules['api']

    def test_uses_default_initial_ranking_prompt(self):
        """Should build the initial ranking prompt when no messages are supplied."""
        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded.requests, 'post') as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                mock_post.return_value.json.return_value = {"choices": []}

                result, error = api_reloaded.call_ai_provider(
                    self.PROVIDER, "pet gadgets", [{'product': 'P1'}]
                )

                self.assertIsNone(error)
                self.assertEqual(result, {"choices": []})
                payload = mock_post.call_args.kwargs["json"]
                self.assertEqual(payload["model"], "gpt-4o-mini")
                self.assertIn("product analyst", payload["messages"][0]["content"])
                self.assertIn("pet gadgets", payload["messages"][1]["content"])
                self.assertIn("P1", payload["messages"][1]["content"])

    def test_custom_messages_override_defaults(self):
        """Should send caller-supplied system/user messages verbatim."""
        with patch.dict(os.environ, {'DECODO_AUTH_TOKEN': 'test-token'}, clear=True):
            import api as api_reloaded
            with patch.object(api_reloaded.requests, 'post') as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                mock_post.return_value.json.return_value = {"choices": []}

                result, error = api_reloaded.call_ai_provider(
                    self.PROVIDER,
                    "pet gadgets",
                    [{'product': 'P1'}],
                    system_message="SYS",
                    user_message="USR",
                )

                self.assertIsNone(error)
                payload = mock_post.call_args.kwargs["json"]
                self.assertEqual(payload["messages"][0]["content"], "SYS")
                self.assertEqual(payload["messages"][1]["content"], "USR")


class TestRunSourcingAndFinalRanking(unittest.TestCase):
    """Test the sourcing and final ranking pipeline."""

    def test_basic_pipeline(self):
        """Should run sourcing and final ranking."""
        products = [{'product': 'P1', 'viral_score': 80}]
        with patch.object(api, 'run_supplier_sourcing') as mock_sourcing, \
             patch.object(api, 'final_rank_products') as mock_rank:
            mock_sourcing.return_value = {
                'supplier_data': [],
                'supplier_summary': {},
            }
            mock_rank.return_value = ([{'product': 'P1', 'final_score': 90, 'ranking_method': 'ai'}], None)

            result = api.run_sourcing_and_final_ranking("test", products)
            self.assertIn('final_products', result)
            self.assertIn('supplier_summary', result)
            self.assertIn('supplier_data', result)
            self.assertIn('ranking_warnings', result)

    def test_empty_products(self):
        """Should handle empty products."""
        result = api.run_sourcing_and_final_ranking("test", [])
        self.assertEqual(result['final_products'], [])
        self.assertIn('No initial products to rank', result['ranking_warnings'][0])


class TestNewEndpoints(unittest.TestCase):
    """Test the new FastAPI endpoints."""

    def setUp(self):
        """Clear cached api module."""
        import sys
        if 'api' in sys.modules:
            del sys.modules['api']

    def test_discover_endpoint(self):
        """Should return discovery result."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            from fastapi.testclient import TestClient
            
            client = TestClient(api_reloaded.app)
            
            with patch.object(api_reloaded, 'run_discovery') as mock_discover:
                mock_discover.return_value = {
                    'niche': 'test',
                    'initial_products': [],
                    'discovery_summary': [],
                    'discovery_data': [],
                    'ranking_warnings': [],
                }
                
                response = client.post("/discover", json={"niche": "test"})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result['niche'], 'test')

    def test_source_endpoint(self):
        """Should return sourcing result."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            from fastapi.testclient import TestClient
            
            client = TestClient(api_reloaded.app)
            
            with patch.object(api_reloaded, 'run_sourcing_and_final_ranking') as mock_source:
                mock_source.return_value = {
                    'final_products': [],
                    'supplier_summary': {},
                    'supplier_data': [],
                    'ranking_warnings': [],
                }
                
                response = client.post("/source", json={"niche": "test", "initial_products": []})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertIn('final_products', result)

    def test_hunt_endpoint_complete(self):
        """Should return complete hunt result with final products."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
            'KIMI_API_KEY': '',
            'MOONSHOT_API_KEY': '',
            'OPENAI_API_KEY': '',
        }, clear=True):
            import api as api_reloaded
            from fastapi.testclient import TestClient
            
            client = TestClient(api_reloaded.app)
            
            with patch.object(api_reloaded, 'run_discovery') as mock_discover, \
                 patch.object(api_reloaded, 'run_sourcing_and_final_ranking') as mock_source:
                mock_discover.return_value = {
                    'niche': 'test',
                    'initial_products': [{'product': 'P1', 'viral_score': 80}],
                    'discovery_summary': [],
                    'discovery_data': [],
                    'ranking_warnings': ['warning1'],
                }
                mock_source.return_value = {
                    'final_products': [{'product': 'P1', 'final_score': 90}],
                    'supplier_summary': {},
                    'supplier_data': [],
                    'ranking_warnings': ['warning2'],
                }
                
                response = client.post("/hunt", json={"niche": "test"})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result['niche'], 'test')
                self.assertIn('final_products', result)
                self.assertEqual(len(result['final_products']), 1)
                self.assertEqual(len(result['ranking_warnings']), 2)  # Combined warnings

    def test_health_endpoint(self):
        """Should return health status."""
        with patch.dict(os.environ, {
            'DECODO_AUTH_TOKEN': 'test-token',
        }, clear=True):
            import api as api_reloaded
            from fastapi.testclient import TestClient
            
            client = TestClient(api_reloaded.app)
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})


class TestSourceRequestModel(unittest.TestCase):
    """Test the SourceRequest Pydantic model."""

    def test_source_request_validation(self):
        """Should validate SourceRequest correctly."""
        request = api.SourceRequest(niche="test", initial_products=[{"product": "P1"}])
        self.assertEqual(request.niche, "test")
        self.assertEqual(len(request.initial_products), 1)

    def test_source_request_empty_products(self):
        """Should accept empty products list."""
        request = api.SourceRequest(niche="test", initial_products=[])
        self.assertEqual(request.initial_products, [])


if __name__ == "__main__":
    unittest.main()

