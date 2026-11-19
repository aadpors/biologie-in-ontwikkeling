import unittest
from ai_adapter import AIConfig, OpenAICompatibleClient, AIUnavailable

class AIAdapterTests(unittest.TestCase):
    def test_external_ai_requires_explicit_consent(self):
        client=OpenAICompatibleClient(AIConfig("https://example.invalid/v1/chat/completions","test-model"))
        with self.assertRaises(AIUnavailable):
            client.review_text("check","testtekst",consent=False)

    def test_external_ai_requires_api_key(self):
        client=OpenAICompatibleClient(AIConfig("https://example.invalid/v1/chat/completions","test-model","BIOLOGIE_TEST_KEY_MISSING"))
        with self.assertRaises(AIUnavailable):
            client.review_text("check","testtekst",consent=True)

if __name__=="__main__": unittest.main()
